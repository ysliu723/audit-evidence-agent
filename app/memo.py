"""The vouching memo a reviewer reads and signs off.

Two ways to write it:
- template_memo: standard wording built from the checks. Always available, no model needed.
- draft_memo: Claude drafts the wording from the same facts. Every figure in the draft (amounts,
  dates, invoice, document, and entry numbers) must appear in those facts; a draft that mentions
  anything else is discarded in favor of the template, and the reason is kept as a warning.

Either way the conclusions come from the checks, and a person signs off.
"""

import json
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, ValidationError

from app.checks import Status
from app.llm import MessagesAPI, cost_usd, strict_json_schema, without_nulls
from app.parsing import all_amounts, all_dates
from app.pipeline import VouchResult

NEXT_STEPS = {
    "VENDOR_IDENTITY": "Confirm the vendor and its bank account with contact details on file, not those on the "
                       "invoice, before paying.",
    "DOCUMENT_LINKS": "Obtain the purchase order and receiving record this invoice belongs to.",
    "QUANTITY": "Obtain proof the billed quantity was received, or a credit note for the difference.",
    "UNIT_PRICE": "Obtain approval for the price change, or a credit note for the overcharge.",
    "ARITHMETIC": "Ask the vendor for a corrected invoice, or explain the difference from the entry.",
    "DATES": "Establish when the goods were ordered and received; if after year end, propose a cut-off adjustment.",
    "APPROVAL": "Obtain approval of the purchase order from someone with authority who did not prepare the entry.",
    "DUPLICATES": "Trace both payments and request a refund or credit if the invoice was paid twice.",
}
UNABLE_STEP = "Review the source document by hand: the automated reading could not be verified."
SUMMARIES = {
    "SUPPORTED": "The entry is supported by the invoice, purchase order, and receiving record, and passed every check.",
    "EXCEPTION": "The entry has exceptions that need follow-up before it can be accepted.",
    "NEEDS_REVIEW": "Some checks could not be completed automatically; a reviewer needs to look at the documents.",
}
DRAFT_SYSTEM_PROMPT = """\
You draft vouching memos for an auditor. You are given a journal entry, the results of automated checks, and the \
quoted evidence. Write a short summary and, for each check that did not pass, a plain explanation for the \
reviewer, plus the next audit steps.

Use only the facts given. Do not mention any amount, date, or document, invoice, or entry number that is not in \
the facts. Do not conclude that fraud occurred; describe what was found and what to do next.
"""


class _Explanation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check: str
    explanation: str


class _Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str
    explanations: list[_Explanation]
    next_steps: list[str]


DRAFT_SCHEMA = strict_json_schema(_Draft)


@dataclass
class MemoFinding:
    check: str
    status: str
    explanation: str
    sources: list[str]


@dataclass
class Memo:
    case_id: str
    entry_id: str
    status: str
    summary: str
    findings: list[MemoFinding]
    next_steps: list[str]
    drafted_by: str  # "template" or the model that drafted it
    warnings: list[str] = field(default_factory=list)
    cost_usd: float = 0.0


def template_memo(result: VouchResult) -> Memo:
    findings, steps = [], []
    for finding in result.report.findings:
        if finding.status == Status.PASS:
            continue
        findings.append(MemoFinding(finding.check, str(finding.status), finding.detail, list(finding.sources)))
        step = NEXT_STEPS[finding.check] if finding.status == Status.FAIL else UNABLE_STEP
        if step not in steps:
            steps.append(step)
    memo = Memo(
        case_id=result.case.case_id,
        entry_id=result.case.entry.entry_id,
        status=result.report.status,
        summary=SUMMARIES[result.report.status],
        findings=findings,
        next_steps=steps or ["No follow-up needed beyond reviewer sign-off."],
        drafted_by="template",
    )
    if "INSTRUCTIONS_IN_DOCUMENT" in result.report.flags:
        memo.warnings.append("A document contains text addressed to automated reviewers. It did not change any check, "
                             "but treat the document as suspect and confirm it with the vendor.")
    return memo


def draft_memo(result: VouchResult, api: MessagesAPI, model: str = "claude-opus-5-5") -> Memo:
    memo = template_memo(result)
    if not memo.findings:
        return memo  # nothing to explain
    facts = facts_text(result)
    request = {
        "model": model,
        "max_tokens": 4000,
        "system": [{"type": "text", "text": DRAFT_SYSTEM_PROMPT}],
        "messages": [{"role": "user", "content": facts}],
        # Writing from given facts is a simple task: low effort keeps it quick and cheap.
        "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": DRAFT_SCHEMA}},
        "betas": ["server-side-fallback-2026-07-01"],
        "fallbacks": "default",
    }
    response = api.create(**request)
    memo.cost_usd = cost_usd(model, response.get("usage") or {})
    if response.get("stop_reason") != "end_turn":
        memo.warnings.append(f"The draft did not finish ({response.get('stop_reason')}); the standard memo is used.")
        return memo
    try:
        text = next(b["text"] for b in (without_nulls(b) for b in response["content"]) if b.get("type") == "text")
        draft = _Draft.model_validate(json.loads(text))
    except (StopIteration, ValueError, ValidationError) as error:
        memo.warnings.append(f"The draft could not be read ({error}); the standard memo is used.")
        return memo

    invented = unsupported_figures(" ".join([draft.summary, *(e.explanation for e in draft.explanations),
                                             *draft.next_steps]), facts)
    if invented:
        memo.warnings.append(
            f"The draft mentioned figures that are not in the evidence ({', '.join(invented)}); "
            "it was discarded and the standard memo is used."
        )
        return memo

    explained = {e.check: e.explanation for e in draft.explanations}
    for unknown in sorted(set(explained) - {f.check for f in memo.findings}):
        memo.warnings.append(f"The draft explained a check that had no issue ({unknown}); that part was dropped.")
    for finding in memo.findings:
        if finding.check in explained:
            finding.explanation = explained[finding.check]
        else:
            memo.warnings.append(f"The draft did not explain {finding.check}; the standard wording is used.")
    memo.summary = draft.summary
    memo.next_steps = draft.next_steps or memo.next_steps
    memo.drafted_by = model
    return memo


def facts_text(result: VouchResult) -> str:
    """Everything the drafter may use, as JSON."""
    facts = {
        "entry": result.case.entry.model_dump(mode="json"),
        "fiscal_year_end": result.case.fiscal_year_end.isoformat(),
        "overall_status": result.report.status,
        "flags": list(result.report.flags),
        "checks": [
            {"check": f.check, "status": str(f.status), "detail": f.detail, "sources": list(f.sources)}
            for f in result.report.findings
        ],
    }
    return json.dumps(facts, indent=1, sort_keys=True)


IDENTIFIERS = re.compile(r"\b(?:DOC-\d+|JE\d{6}|[A-Z]{2,4}-\d{3,})\b")


def unsupported_figures(text: str, facts: str) -> list[str]:
    """Amounts, dates, and identifiers in `text` that do not appear in `facts`."""
    known_amounts, known_dates = set(all_amounts(facts)), set(all_dates(facts))
    problems = [f"{amount:,.2f}" for amount in all_amounts(text) if amount not in known_amounts]
    problems += [day.isoformat() for day in all_dates(text) if day not in known_dates]
    problems += [identifier for identifier in IDENTIFIERS.findall(text) if identifier not in facts]
    return sorted(set(problems))


def render(memo: Memo) -> str:
    """The memo as plain text, for the command line and for review."""
    lines = [
        f"Vouching memo: {memo.entry_id} ({memo.case_id})",
        f"Status: {memo.status}",
        f"Drafted by: {memo.drafted_by} - requires reviewer sign-off",
        "",
        memo.summary,
    ]
    for finding in memo.findings:
        lines += ["", f"[{finding.status}] {finding.check}", f"  {finding.explanation}"]
        lines += [f"  Source: {source}" for source in finding.sources]
    lines += ["", "Next steps:"] + [f"  - {step}" for step in memo.next_steps]
    if memo.warnings:
        lines += ["", "Warnings:"] + [f"  - {warning}" for warning in memo.warnings]
    return "\n".join(lines)
