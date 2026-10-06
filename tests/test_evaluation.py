import json

import pytest

from app.evidence import EvidenceStore, load_cases, load_ground_truth
from app.extractors.claude_judge import JUDGE_PROMPT, JUDGED_SCHEMA, ClaudeJudgeExtractor
from app.extractors.rules import RuleBasedExtractor
from evaluation.evaluate import OracleExtractor, evaluate, main, report
from evaluation.oracle import oracle_extraction
from tests.scripted import ScriptedAPI, response, thinking, tool_turn


@pytest.fixture(scope="module")
def store():
    return EvidenceStore.load()


@pytest.fixture(scope="module")
def cases():
    return load_cases()


@pytest.fixture(scope="module")
def truths():
    return load_ground_truth()


def test_the_oracle_gets_every_case_right(store, cases, truths):
    scored = evaluate(cases, truths, OracleExtractor(store, truths), store)
    assert all(s.correct for s in scored)
    text = report(scored, "oracle", store)
    assert "| Cases correct | 100% (80/80) |" in text
    assert "| Citations that hold up | 100%" in text


def test_the_rules_baseline_breaks_on_the_unseen_layout(store, cases, truths):
    scored = evaluate(cases, truths, RuleBasedExtractor(store), store)
    text = report(scored, "rules", store)
    assert "| A | 100% (22/22) |" in text and "| B | 100% (29/29) |" in text
    assert "| C | 0% (0/23) |" in text
    assert "## Cases it got wrong" in text


def test_a_live_run_needs_confirmation_and_makes_no_call_without_it(capsys):
    assert main(["--extractor", "claude", "--cases", "3"]) == 2
    assert "Add --yes" in capsys.readouterr().err


def test_the_judge_variant_gets_the_tools_and_the_registers(store, cases, truths):
    truth = next(t for t in truths.values() if t.scenario == "DUPLICATE_INVOICE")
    case = next(c for c in cases if c.case_id == truth.case_id)
    extraction = oracle_extraction(case, truth, store).model_dump(mode="json")
    verdicts = [{"check": "DUPLICATE_INVOICE", "status": "FAIL", "reason": "already paid"},
                {"check": "AMOUNT_MATCH", "status": "PASS", "reason": "equal"}]
    text = json.dumps({**extraction, "verdicts": verdicts, "overall_status": "EXCEPTION"})
    answer = response([thinking(), {"type": "text", "text": text}], "end_turn")
    api = ScriptedAPI([tool_turn(("search_documents", {"query": truth.invoice_number})), answer])

    [scored] = evaluate([case], truths, ClaudeJudgeExtractor(store, api), store)

    first = api.requests[0]
    assert "Paid-invoice register" in first["messages"][0]["content"]
    assert "Vendor master" in first["messages"][0]["content"]
    assert first["output_config"]["format"]["schema"] == JUDGED_SCHEMA
    assert "Do not decide" not in JUDGE_PROMPT
    assert (scored.status, scored.failures) == ("EXCEPTION", ["DUPLICATE_INVOICE"])  # the model's verdicts are scored
    assert scored.correct
