"""A stand-in for the Claude API that plays back a script of responses, for tests without an API key."""

import copy

from app.extraction import Findings


class ScriptedAPI:
    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.requests: list[dict] = []

    def create(self, **request) -> dict:
        self.requests.append(copy.deepcopy(request))
        if not self.responses:
            raise AssertionError("the script ran out of responses")
        return self.responses.pop(0)


USAGE = {"input_tokens": 1000, "output_tokens": 500, "cache_creation_input_tokens": 1000, "cache_read_input_tokens": 2000}


def response(content: list[dict], stop_reason: str, usage: dict | None = None, **extra) -> dict:
    return {"id": "msg_test", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": content,
            "stop_reason": stop_reason, "usage": usage or dict(USAGE), **extra}


def thinking() -> dict:
    # What adaptive thinking looks like by default: an empty summary and a signature.
    return {"type": "thinking", "thinking": "", "signature": "test-signature"}


def tool_turn(*calls: tuple[str, dict]) -> dict:
    blocks = [{"type": "tool_use", "id": f"toolu_{n}", "name": name, "input": arguments}
              for n, (name, arguments) in enumerate(calls)]
    return response([thinking(), *blocks], "tool_use")


def submit_turn(findings: Findings | dict) -> dict:
    data = findings.model_dump(mode="json") if isinstance(findings, Findings) else findings
    return tool_turn(("submit_findings", data))


def text_turn(text: str) -> dict:
    return response([thinking(), {"type": "text", "text": text}], "end_turn")
