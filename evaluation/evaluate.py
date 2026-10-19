"""Measure an extractor on the labeled cases, check by check.

    python -m evaluation.evaluate --extractor oracle                     # perfect reading: what the checks reach
    python -m evaluation.evaluate --extractor rules                      # the template baseline, no AI
    python -m evaluation.evaluate --extractor claude --split dev --cases 5 --record --yes   # live: costs money
    python -m evaluation.evaluate --extractor claude --record --yes      # all 60 held-out cases, live
    python -m evaluation.evaluate --extractor claude --replay            # again from the recordings, free
    python -m evaluation.evaluate --extractor claude --profile baseline --record --yes      # the other retrieval profile

Each held-out case has eight checks, so 60 cases give 480 decisions. A decision is right only if the check's
result equals the label: PASS, FAIL, or UNABLE. Answering UNABLE (abstaining) when the evidence was clear
counts as wrong; abstaining is right only where the label says the evidence cannot be read (a scanned invoice).

Writes docs/evaluation-<name>.md and docs/results/<name>.json (one record per case, with cost and latency),
which evaluation/compare.py reads to compare two runs.
"""

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.checks import CHECK_CODES
from app.domain import Case, GroundTruth
from app.evidence import EvidenceStore, load_cases, load_ground_truth
from app.extractors.base import ExtractionRun
from app.pipeline import VouchResult, vouch
from evaluation.oracle import oracle_findings

ROOT = Path(__file__).resolve().parent.parent
ESTIMATED_COST_PER_CASE = (0.05, 0.30)  # US dollars, a rough guide for the warning before a live run


class OracleExtractor:
    name = "oracle"

    def __init__(self, truths: dict[str, GroundTruth]):
        self.truths = truths

    def extract(self, case: Case) -> ExtractionRun:
        return ExtractionRun(findings=oracle_findings(case, self.truths[case.case_id]))


@dataclass
class Scored:
    truth: GroundTruth
    result: VouchResult

    @property
    def verdicts(self) -> dict[str, str]:
        return self.result.report.verdicts

    @property
    def wrong(self) -> list[str]:
        return [c for c in CHECK_CODES if self.verdicts.get(c) != self.truth.expected[c]]

    @property
    def abstained_wrongly(self) -> list[str]:
        return [c for c in self.wrong if self.verdicts.get(c) == "UNABLE"]

    def record(self) -> dict:
        run = self.result.run
        return {"case_id": self.truth.case_id, "split": self.truth.split, "scenario": self.truth.scenario,
                "layout": self.truth.layout, "unseen_layout": self.truth.unseen_layout,
                "expected": self.truth.expected, "verdicts": self.verdicts, "wrong": self.wrong,
                "status": self.result.report.status, "error": run.error, "model": run.model,
                "model_calls": run.model_calls, "tool_calls": len(run.tool_calls),
                "refused_calls": run.refused_calls, "corrections": run.corrections,
                "input_tokens": run.input_tokens, "output_tokens": run.output_tokens,
                "cache_read_tokens": run.cache_read_tokens, "cache_write_tokens": run.cache_write_tokens,
                "cost_usd": round(run.cost_usd, 6), "seconds": round(run.seconds, 3)}


def evaluate(cases: list[Case], extractor, store: EvidenceStore, truths: dict[str, GroundTruth]) -> list[Scored]:
    scored = []
    for case in cases:
        scored.append(Scored(truths[case.case_id], vouch(case, extractor, store)))
        print(f"  {case.case_id}  {len(CHECK_CODES) - len(scored[-1].wrong)}/{len(CHECK_CODES)}", file=sys.stderr)
    return scored


def accuracy(scored: list[Scored]) -> tuple[int, int]:
    total = len(scored) * len(CHECK_CODES)
    return total - sum(len(s.wrong) for s in scored), total


def percent(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "n/a"


def report(name: str, scored: list[Scored], split: str, details: str) -> str:
    right, total = accuracy(scored)
    familiar = [s for s in scored if not s.truth.unseen_layout]
    unseen = [s for s in scored if s.truth.unseen_layout]
    f_right, f_total = accuracy(familiar)
    u_right, u_total = accuracy(unseen)
    whole_cases = sum(1 for s in scored if not s.wrong)
    abstentions = sum(len(s.abstained_wrongly) for s in scored)
    out = [f"# Evaluation: {name}", "", f"{details}. Split: {split}, {len(scored)} cases. Run on {date.today()}.", "",
           "| Measure | Result |", "|---|---|",
           f"| Check-level accuracy | **{percent(right, total)}** ({right}/{total} decisions) |",
           f"| Familiar invoice layouts (A, B) | {percent(f_right, f_total)} ({f_right}/{f_total}) |",
           f"| Unseen invoice layouts (C, D, E) | {percent(u_right, u_total)} ({u_right}/{u_total}) |",
           f"| Cases with all eight checks right | {whole_cases}/{len(scored)} |",
           f"| Wrong abstentions (UNABLE on a clear answer; counted as errors) | {abstentions} |"]
    runs = [s.result.run for s in scored]
    if any(r.model_calls for r in runs):
        costs = [r.cost_usd for r in runs]
        seconds = sorted(r.seconds for r in runs)
        p95 = seconds[min(len(seconds) - 1, int(round(0.95 * (len(seconds) - 1))))]
        out += [f"| Mean cost per case | ${statistics.mean(costs):.4f} (total ${sum(costs):.2f}; estimate from token "
                "counts and list prices) |",
                f"| Latency per case | median {statistics.median(seconds):.1f} s, p95 {p95:.1f} s |",
                f"| Model calls per case | mean {statistics.mean(r.model_calls for r in runs):.1f} |",
                f"| Citations sent back for correction | {sum(sum(r.corrections.values()) for r in runs)} |",
                f"| Tool calls refused by the backend | {sum(len(r.refused_calls) for r in runs)} |",
                f"| Runs that stopped early (go to a person) | {sum(1 for r in runs if r.error)} |"]
    out += ["", "## By check", "", "| Check | Right |", "|---|---|"]
    for check in CHECK_CODES:
        hits = sum(1 for s in scored if check not in s.wrong)
        out.append(f"| {check} | {hits}/{len(scored)} |")
    out += ["", "## By scenario", "", "| Scenario | Cases | Decisions right |", "|---|---|---|"]
    by_scenario: dict[str, list[Scored]] = defaultdict(list)
    for s in scored:
        by_scenario[s.truth.scenario].append(s)
    for scenario, group in sorted(by_scenario.items()):
        g_right, g_total = accuracy(group)
        out.append(f"| {scenario} | {len(group)} | {g_right}/{g_total} |")
    mistakes = [(s, c) for s in scored for c in s.wrong]
    if mistakes:
        out += ["", "## Wrong decisions", "", "| Case | Scenario | Layout | Check | Expected | Got | Why |",
                "|---|---|---|---|---|---|---|"]
        for s, check in mistakes:
            detail = s.result.report.finding(check).detail.replace("|", "/")[:140]
            out.append(f"| {s.truth.case_id} | {s.truth.scenario} | {s.truth.layout} | {check} | "
                       f"{s.truth.expected[check]} | {s.verdicts[check]} | {detail} |")
    errors = Counter(s.result.run.error for s in scored if s.result.run.error)
    if errors:
        out += ["", "## Runs that stopped early", ""] + [f"- {error}: {n}" for error, n in errors.most_common()]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate an extractor on the labeled vouching cases.")
    parser.add_argument("--extractor", choices=["oracle", "rules", "claude"], required=True)
    parser.add_argument("--split", choices=["dev", "heldout", "all"], default="heldout")
    parser.add_argument("--profile", choices=["optimized", "baseline"], default="optimized")
    parser.add_argument("--cases", type=int, help="only the first N cases of the split")
    parser.add_argument("--record", action="store_true", help="live run that saves every request and response")
    parser.add_argument("--replay", action="store_true", help="answer from the recordings only; no API key")
    parser.add_argument("--yes", action="store_true", help="confirm a live run, which costs money")
    parser.add_argument("--name", help="report name (default: from the extractor and profile)")
    args = parser.parse_args(argv)

    store, truths = EvidenceStore.load(), load_ground_truth()
    cases = [c for c in load_cases() if args.split == "all" or truths[c.case_id].split == args.split]
    cases = cases[: args.cases] if args.cases else cases
    name = args.name or (args.extractor if args.extractor != "claude" else f"claude-{args.profile}")

    if args.extractor == "oracle":
        extractor, details = OracleExtractor(truths), "Oracle: the true values, read perfectly"
    elif args.extractor == "rules":
        from app.extractors.rules import RuleBasedExtractor

        extractor, details = RuleBasedExtractor(store), "Template baseline: fixed labels for layouts A and B, no AI"
    else:
        from app.extractors.claude import ClaudeExtractor
        from app.llm import AnthropicAPI, RecordingAPI, ReplayAPI

        if args.replay:
            api = ReplayAPI()
        else:
            low, high = (len(cases) * c for c in ESTIMATED_COST_PER_CASE)
            if not args.yes:
                print(f"A live run of {len(cases)} cases calls the Claude API and costs money: roughly "
                      f"${low:.2f}-${high:.2f}. Add --yes to run it (and --record to keep the answers).")
                return 2
            api = RecordingAPI(AnthropicAPI()) if args.record else AnthropicAPI()
        extractor = ClaudeExtractor(store, api, profile=args.profile)
        details = f"Claude ({extractor.model}, effort {extractor.effort}), {args.profile} retrieval"

    scored = evaluate(cases, extractor, store, truths)
    docs = ROOT / "docs"
    (docs / "results").mkdir(parents=True, exist_ok=True)
    (docs / f"evaluation-{name}.md").write_text(report(name, scored, args.split, details), encoding="utf-8")
    (docs / "results" / f"{name}.json").write_text(json.dumps([s.record() for s in scored], indent=1), encoding="utf-8")
    right, total = accuracy(scored)
    print(f"{name}: {right}/{total} decisions right ({percent(right, total)}); wrote docs/evaluation-{name}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
