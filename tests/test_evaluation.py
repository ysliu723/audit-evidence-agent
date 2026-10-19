"""Scoring: eight decisions per case, abstaining on a clear answer is wrong, unseen layouts counted apart."""

import json

from evaluation.compare import compare
from evaluation.evaluate import OracleExtractor, Scored, accuracy, evaluate, main, report
from tests.helpers import cases, store, truths


def heldout():
    return [c for c in cases().values() if truths()[c.case_id].split == "heldout"]


def test_the_oracle_scores_every_decision():
    scored = evaluate(heldout(), OracleExtractor(truths()), store(), truths())
    assert accuracy(scored) == (480, 480)


def test_the_template_baseline_is_perfect_on_familiar_layouts_and_breaks_on_unseen_ones():
    from app.extractors.rules import RuleBasedExtractor

    scored = evaluate(heldout(), RuleBasedExtractor(store()), store(), truths())
    familiar = [s for s in scored if not s.truth.unseen_layout]
    unseen = [s for s in scored if s.truth.unseen_layout]
    assert accuracy(familiar) == (400, 400) and accuracy(unseen) == (25, 80)
    assert accuracy(scored) == (425, 480)
    assert all(s.abstained_wrongly == s.wrong for s in scored)  # it never guesses: every miss is an abstention
    text = report("rules", scored, "heldout", "Template baseline")
    assert "| Check-level accuracy | **88.5%** (425/480 decisions) |" in text
    assert "| Unseen invoice layouts (C, D, E) | 31.2% (25/80) |" in text


def test_an_abstention_on_a_clear_answer_counts_as_wrong():
    case = heldout()[0]
    truth = truths()[case.case_id]

    class Stub:
        def __init__(self, verdicts):
            from app.checks import CheckReport, Finding, Status
            self.report = CheckReport(tuple(Finding(c, Status(v), "") for c, v in verdicts.items()), "NEEDS_REVIEW")
            from app.extractors.base import ExtractionRun
            from app.extraction import Findings
            self.run = ExtractionRun(findings=Findings(invoice=None, purchase_order=None, receiving_record=None,
                                                       contract=None, notes=""))

    abstaining = Scored(truth, Stub({c: "UNABLE" for c in truth.expected}))
    expected_unable = sum(v == "UNABLE" for v in truth.expected.values())
    assert len(abstaining.wrong) == 8 - expected_unable == len(abstaining.abstained_wrongly)


def test_a_live_run_needs_confirmation(capsys):
    assert main(["--extractor", "claude", "--cases", "2"]) == 2
    assert "costs money" in capsys.readouterr().out


def test_two_runs_are_compared_on_accuracy_cost_and_latency():
    record = {"case_id": "CASE-001", "expected": {"A": "PASS", "B": "PASS"}, "wrong": [], "input_tokens": 1000,
              "cache_read_tokens": 0, "cache_write_tokens": 0}
    first = [{**record, "case_id": f"CASE-{n}", "cost_usd": 0.10, "seconds": 30.0 + n} for n in range(10)]
    second = [{**record, "case_id": f"CASE-{n}", "cost_usd": 0.08, "seconds": 20.0 + n, "input_tokens": 600}
              for n in range(10)]
    table = compare(first, second, ("claude-baseline", "claude-optimized"))
    assert "| Mean cost per case | $0.1000 | $0.0800 | -20% |" in table
    assert "| Median latency | 34.5 s | 24.5 s | -29% |" in table
    assert json.dumps(first)  # records are plain JSON
