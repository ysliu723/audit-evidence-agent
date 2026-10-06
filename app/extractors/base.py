"""What every extractor returns, so the evaluation can compare them on equal terms."""

from dataclasses import dataclass, field

from app.extraction import Extraction


@dataclass
class ExtractionRun:
    extraction: Extraction
    tool_calls: list[dict] = field(default_factory=list)  # [{"tool": "search_documents", "input": {...}}]
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    seconds: float = 0.0
    model: str | None = None
    error: str | None = None  # set when the extractor gave up, e.g. a refusal or no usable answer
    # Only for the comparison experiment, where the model also decides the checks itself.
    model_verdicts: dict[str, str] | None = None  # check code -> PASS / FAIL / UNABLE / NOT_APPLICABLE
    model_status: str | None = None
