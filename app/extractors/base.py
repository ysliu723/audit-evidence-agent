"""What every extractor returns, so the evaluation can compare them on equal terms."""

from dataclasses import dataclass, field

from app.extraction import Findings


@dataclass
class ExtractionRun:
    findings: Findings
    tool_calls: list[dict] = field(default_factory=list)  # [{"tool": "read_page", "input": {...}}]
    refused_calls: list[dict] = field(default_factory=list)  # tool calls the backend refused, and why
    corrections: dict[str, int] = field(default_factory=dict)  # field -> times the model was asked to fix it
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    seconds: float = 0.0
    model: str | None = None
    error: str | None = None  # set when the extractor gave up: a refusal, a limit reached, no usable answer
