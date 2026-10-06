"""Measure an extractor on the labeled cases.

    python -m evaluation.evaluate --extractor rules             # no AI: the baseline
    python -m evaluation.evaluate --extractor oracle            # perfect extraction: what the checks can reach
    python -m evaluation.evaluate --extractor claude --replay   # from data/recordings/, no API key needed
    python -m evaluation.evaluate --extractor claude --record --yes        # live: costs money, saves recordings
    python -m evaluation.evaluate --extractor claude-judge --record --yes  # the model also decides the checks

Writes docs/evaluation-<extractor>.md. A case counts as correct only if the
overall status AND the exact set of failed checks match the ground truth.
"""

import argparse
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.checks import CheckReport, Finding, Status
from app.citations import citation_problem
from app.domain import Case, GroundTruth
from app.evidence import EvidenceStore, load_cases, load_ground_truth
from app.extractors.base import ExtractionRun
from app.parsing import normalize_name
from app.pipeline import VouchResult, vouch
from evaluation.oracle import oracle_extraction

# A rough guide for the live-run warning, from the size of the cases (about 3-5 turns each); measure to be sure.
ESTIMATED_COST_PER_CASE = {"claude": (0.05, 0.25), "claude-judge": (0.08, 0.35)}
FIELDS = ["vendor_name", "invoice_number", "invoice_date", "total_amount", "bank_last4"]


@dataclass
class Scored:
    truth: GroundTruth
    result: VouchResult

    @property
    def status(self) -> str:
        return self.result.report.status

    @property
    def failures(self) -> list[str]:
        return sorted(self.result.report.failures)

    @property
    def correct(self) -> bool:
        return self.status == self.truth.expected_status and self.failures == sorted(self.truth.expected_failures)


class OracleExtractor:
    name = "oracle"

    def __init__(self, store: EvidenceStore, truths: dict[str, GroundTruth]):
        self.store, self.truths = store, truths

    def extract(self, case: Case) -> ExtractionRun:
        return ExtractionRun(extraction=oracle_extraction(case, self.truths[case.case_id], self.store))


def judged_result(result: VouchResult) -> VouchResult:
    """For the comparison experiment: score the model's own verdicts instead of the code's checks."""
    run = result.run
    if run.error or run.model_verdicts is None:
        return result
    findings = tuple(Finding(check, Status(status), "decided by the model") for check, status in run.model_verdicts.items())
    return VouchResult(case=result.case, run=run, report=CheckReport(findings, run.model_status or "NEEDS_REVIEW"))


def evaluate(cases: list[Case], truths: dict[str, GroundTruth], extractor, store: EvidenceStore) -> list[Scored]:
    scored = []
    for case in cases:
        result = vouch(case, extractor, store)
        if extractor.name == "claude-judge":
            result = judged_result(result)
        scored.append(Scored(truths[case.case_id], result))
    return scored


def percent(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}% ({part}/{whole})" if whole else "-"


def table(headers: list[str], rows: list[list[str]]) -> str:
    return "\n".join(["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
                     + ["| " + " | ".join(row) + " |" for row in rows])


def field_value(truth: GroundTruth, name: str) -> str | None:
    value = getattr(truth, name)
    return None if value is None else (value.isoformat() if isinstance(value, date) else str(value))


def report(scored: list[Scored], extractor_name: str, store: EvidenceStore) -> str:
    total = len(scored)
    correct = sum(s.correct for s in scored)

    by_scenario, by_layout = defaultdict(list), defaultdict(list)
    for s in scored:
        by_scenario[s.truth.scenario].append(s.correct)
        by_layout[s.truth.template or "none (no invoice)"].append(s.correct)

    found = right_document = 0
    field_right, field_total = Counter(), Counter()
    citations_ok = citations_total = 0
    for s in scored:
        invoice = s.result.run.extraction.invoice
        if s.truth.support_document_id is None or invoice is None:
            continue
        found += 1
        right_document += invoice.document_id == s.truth.support_document_id
        for name in FIELDS:
            cited = getattr(invoice, name)
            expected = field_value(s.truth, name)
            if expected is None:
                continue
            field_total[name] += 1
            got = cited.value if cited else None
            if name == "vendor_name":
                field_right[name] += got is not None and normalize_name(got) == normalize_name(expected)
            else:
                field_right[name] += got == expected
            if cited is not None:
                citations_total += 1
                kind = {"invoice_date": "date", "total_amount": "amount"}.get(name, "text")
                citations_ok += citation_problem(store, invoice.document_id, cited, kind) is None
        field_total["service_category"] += 1
        field_right["service_category"] += invoice.service_category == s.truth.service_category

    lookalikes = [s for s in scored if s.truth.scenario == "LOOKALIKE_VENDOR"]
    caught = sum("VENDOR_APPROVED" in s.failures for s in lookalikes)
    injections = [s for s in scored if s.truth.scenario == "PROMPT_INJECTION"]
    not_fooled = sum(
        s.result.run.extraction.invoice is not None
        and s.result.run.extraction.invoice.total_amount.value == str(s.truth.total_amount)
        for s in injections
    )
    supported = [s for s in scored if s.truth.scenario == "SUPPORTED"]
    false_alarms = sum(s.status != "SUPPORTED" for s in supported)

    runs = [s.result.run for s in scored]
    cost = sum(r.cost_usd for r in runs)
    errors = Counter(r.error for r in runs if r.error)
    lines = [
        f"# Evaluation: {extractor_name}",
        "",
        f"{total} synthetic cases, produced by `python -m evaluation.evaluate --extractor {extractor_name}`. "
        "A case is correct only if the overall status and the exact set of failed checks both match.",
        "",
        "## Headline",
        "",
        table(["Measure", "Result"], [
            ["Cases correct", percent(correct, total)],
            ["Look-alike vendors caught", percent(caught, len(lookalikes))],
            ["Injected invoices read correctly (not fooled)", percent(not_fooled, len(injections))],
            ["Supported entries wrongly flagged", percent(false_alarms, len(supported))],
            ["Citations that hold up", percent(citations_ok, citations_total)],
            ["Runs that ended in an error", str(sum(errors.values()))],
        ]),
        "",
        "## By scenario",
        "",
        table(["Scenario", "Correct"], [[name, percent(sum(v), len(v))] for name, v in sorted(by_scenario.items())]),
        "",
        "## By invoice layout",
        "",
        table(["Layout", "Correct"], [[name, percent(sum(v), len(v))] for name, v in sorted(by_layout.items())]),
        "",
        "## Extraction",
        "",
        f"Invoices found for cases that have one: {found}; the right document: {percent(right_document, found)}.",
        "",
        table(["Field", "Correct"], [[name, percent(field_right[name], field_total[name])]
                                     for name in [*FIELDS, "service_category"]]),
        "",
        "## Cost and speed",
        "",
        table(["Measure", "Result"], [
            ["Total cost (estimated)", f"${cost:.2f}"],
            ["Cost per case", f"${cost / total:.4f}" if total else "-"],
            ["Input / output tokens", f"{sum(r.input_tokens for r in runs):,} / {sum(r.output_tokens for r in runs):,}"],
            ["Cache read / write tokens",
             f"{sum(r.cache_read_tokens for r in runs):,} / {sum(r.cache_write_tokens for r in runs):,}"],
            ["Seconds per case", f"{sum(r.seconds for r in runs) / total:.2f}" if total else "-"],
            ["Tool calls per case", f"{sum(len(r.tool_calls) for r in runs) / total:.1f}" if total else "-"],
        ]),
    ]
    if errors:
        lines += ["", "Errors: " + "; ".join(f"{error} ({count})" for error, count in errors.most_common())]
    wrong = [s for s in scored if not s.correct]
    if wrong:
        lines += ["", "## Cases it got wrong", "",
                  table(["Case", "Scenario", "Layout", "Expected", "Got"], [
                      [s.truth.case_id, s.truth.scenario, s.truth.template or "-",
                       f"{s.truth.expected_status} {sorted(s.truth.expected_failures)}", f"{s.status} {s.failures}"]
                      for s in wrong
                  ])]
    return "\n".join(lines) + "\n"


def make_extractor(name: str, store: EvidenceStore, truths, record: bool, replay: bool):
    if name == "rules":
        from app.extractors.rules import RuleBasedExtractor

        return RuleBasedExtractor(store)
    if name == "oracle":
        return OracleExtractor(store, truths)
    from app.llm import AnthropicAPI, RecordingAPI, ReplayAPI

    api = ReplayAPI() if replay else (RecordingAPI(AnthropicAPI()) if record else AnthropicAPI())
    if name == "claude":
        from app.extractors.claude import ClaudeExtractor

        return ClaudeExtractor(store, api)
    if name == "claude-judge":
        from app.extractors.claude_judge import ClaudeJudgeExtractor

        return ClaudeJudgeExtractor(store, api)
    raise SystemExit(f"unknown extractor {name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate an extractor on the labeled cases.")
    parser.add_argument("--extractor", default="rules", choices=["rules", "oracle", "claude", "claude-judge"])
    parser.add_argument("--cases", type=int, default=None, help="only the first N cases (cheaper live runs)")
    parser.add_argument("--replay", action="store_true", help="answer from recordings; no API calls")
    parser.add_argument("--record", action="store_true", help="save every live exchange for later replay")
    parser.add_argument("--yes", action="store_true", help="confirm a live run that costs money")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    store, truths = EvidenceStore.load(), load_ground_truth()
    cases = load_cases()[: args.cases]
    live = args.extractor.startswith("claude") and not args.replay
    if live and not args.yes:
        low, high = ESTIMATED_COST_PER_CASE[args.extractor]
        print(f"A live run calls the Claude API for {len(cases)} cases: roughly ${low * len(cases):.0f}-"
              f"${high * len(cases):.0f}. Add --yes to go ahead (and --record to keep the responses).",
              file=sys.stderr)
        return 2

    scored = evaluate(cases, truths, make_extractor(args.extractor, store, truths, args.record, args.replay), store)
    text = report(scored, args.extractor, store)
    out = args.out or Path("docs") / f"evaluation-{args.extractor}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"Written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
