"""Talking to Claude: the real API, plus recording and replay so tests and demos need no API key.

Everything here works with plain dicts (the JSON the API sends and receives),
so a recorded response replays exactly like a live one.

    AnthropicAPI   calls Claude (needs ANTHROPIC_API_KEY or an `ant auth login` profile)
    RecordingAPI   calls another API and saves every request and response to data/recordings/
    ReplayAPI      answers from data/recordings/ only; never touches the network
"""

import copy
import hashlib
import json
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

RECORDINGS_DIR = Path(__file__).resolve().parent.parent / "data" / "recordings"

# US dollars per million tokens: input, output, cache write (5-minute), cache read.
# A request answered by a fallback model is billed at that model's rates, so treat costs as estimates.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 5.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.20),
    "claude-haiku-4-5": (1.00, 5.00, 1.25, 0.10),
}


class MessagesAPI(Protocol):
    def create(self, **request) -> dict: ...


class AnthropicAPI:
    def __init__(self, client=None):
        if client is None:
            import anthropic

            client = anthropic.Anthropic()  # credentials from the environment, never from code
        self.client = client

    def create(self, **request) -> dict:
        # The beta endpoint, because the request opts into server-side refusal fallbacks.
        return self.client.beta.messages.create(**request).to_dict()


def request_key(request: dict) -> str:
    """The same request always gives the same key, so a recording can be found again."""
    canonical = json.dumps(request, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:24]


class RecordingAPI:
    def __init__(self, inner: MessagesAPI, directory: Path = RECORDINGS_DIR):
        self.inner = inner
        self.directory = directory

    def create(self, **request) -> dict:
        response = self.inner.create(**request)
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{request_key(request)}.json"
        path.write_text(json.dumps({"request": request, "response": response}, indent=1, default=str), encoding="utf-8")
        return response


class MissingRecording(LookupError):
    pass


class ReplayAPI:
    def __init__(self, directory: Path = RECORDINGS_DIR):
        self.directory = directory

    def create(self, **request) -> dict:
        path = self.directory / f"{request_key(request)}.json"
        if not path.exists():
            raise MissingRecording(
                f"no recording for this request ({path.name}); record it first with a live run (--record)"
            )
        return json.loads(path.read_text(encoding="utf-8"))["response"]


def cost_usd(model: str, usage: dict) -> float:
    input_price, output_price, write_price, read_price = PRICES.get(model, PRICES["claude-opus-5-5"])
    return (
        (usage.get("input_tokens") or 0) * input_price
        + (usage.get("output_tokens") or 0) * output_price
        + (usage.get("cache_creation_input_tokens") or 0) * write_price
        + (usage.get("cache_read_input_tokens") or 0) * read_price
    ) / 1_000_000


def without_nulls(block: dict) -> dict:
    """A content block ready to send back: the same block, minus fields the API returned as null."""
    return {key: value for key, value in block.items() if value is not None}


def strict_json_schema(model: type[BaseModel]) -> dict:
    """A Pydantic model's JSON schema in the form structured outputs requires.

    Every object lists all its properties as required and allows no others;
    references to shared definitions are written out in place.
    """
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})

    def rewrite(node):
        if isinstance(node, list):
            return [rewrite(item) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            target = rewrite(copy.deepcopy(definitions[node["$ref"].split("/")[-1]]))
            if "description" in node:
                target["description"] = node["description"]
            return target
        result = {}
        for key, value in node.items():
            if key in ("title", "default"):
                continue
            if key == "properties":
                result[key] = {name: rewrite(child) for name, child in value.items()}
            else:
                result[key] = rewrite(value)
        if result.get("type") == "object":
            result["additionalProperties"] = False
            result["required"] = list(result.get("properties", {}))
        return result

    return rewrite(schema)
