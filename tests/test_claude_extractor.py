"""The Claude extractor's loop, request shape, and record/replay, with a scripted API (no key, no network)."""

import pytest

from app.evidence import EvidenceStore, load_cases, load_ground_truth
from app.extractors.claude import EXTRACTION_SCHEMA, MAX_TURNS, ClaudeExtractor
from app.llm import MissingRecording, RecordingAPI, ReplayAPI, strict_json_schema
from app.extraction import Extraction
from app.pipeline import vouch
from evaluation.oracle import oracle_extraction
from tests.scripted import ScriptedAPI, final_turn, response, thinking, tool_turn


@pytest.fixture(scope="module")
def store():
    return EvidenceStore.load()


@pytest.fixture(scope="module")
def cases():
    return {case.case_id: case for case in load_cases()}


@pytest.fixture(scope="module")
def truths():
    return load_ground_truth()


def a_case(cases, truths, scenario="SUPPORTED"):
    truth = next(t for t in truths.values() if t.scenario == scenario)
    return cases[truth.case_id], truth


def search_read_answer(store, case, truth):
    """The script of a typical run: search, read the invoice and the contract, answer."""
    return [
        tool_turn(("search_documents", {"query": f"{truth.vendor_name} {truth.invoice_number}"})),
        tool_turn(("read_document", {"document_id": truth.support_document_id}),
                  ("read_document", {"document_id": truth.contract_document_id})),
        final_turn(oracle_extraction(case, truth, store)),
    ]


def test_the_request_follows_the_api_guidance(store, cases, truths):
    case, truth = a_case(cases, truths)
    api = ScriptedAPI(search_read_answer(store, case, truth))
    ClaudeExtractor(store, api).extract(case)

    first = api.requests[0]
    assert first["model"] == "claude-opus-5-5"
    assert first["output_config"]["effort"] == "medium"  # set explicitly, not left to the default
    assert first["output_config"]["format"] == {"type": "json_schema", "schema": EXTRACTION_SCHEMA}
    assert all(tool["strict"] is True for tool in first["tools"])
    assert first["cache_control"] == {"type": "ephemeral"}
    assert (first["betas"], first["fallbacks"]) == (["server-side-fallback-2026-07-01"], "default")
    assert "thinking" not in first  # adaptive thinking is always on for this model; nothing to configure
    assert case.entry.entry_id in first["messages"][0]["content"]


def test_the_loop_runs_the_tools_and_returns_the_cited_answer(store, cases, truths):
    case, truth = a_case(cases, truths)
    api = ScriptedAPI(search_read_answer(store, case, truth))

    result = vouch(case, ClaudeExtractor(store, api), store)

    assert [call["tool"] for call in result.run.tool_calls] == ["search_documents", "read_document", "read_document"]
    second = api.requests[1]["messages"]
    assert second[1]["role"] == "assistant" and second[1]["content"][0]["type"] == "thinking"  # sent back unchanged
    search_result = second[2]["content"][0]
    assert search_result["type"] == "tool_result" and truth.support_document_id in search_result["content"]
    reads = api.requests[2]["messages"][4]["content"]
    assert len(reads) == 2 and all("[page 1]" in r["content"] for r in reads)  # both results in one message
    assert result.run.extraction.invoice.invoice_number.value == truth.invoice_number
    assert result.report.status == "SUPPORTED"


def test_usage_and_cost_add_up_over_the_turns(store, cases, truths):
    case, truth = a_case(cases, truths)
    run = ClaudeExtractor(store, ScriptedAPI(search_read_answer(store, case, truth))).extract(case)

    assert (run.input_tokens, run.output_tokens, run.cache_write_tokens, run.cache_read_tokens) == (3000, 1500, 3000, 6000)
    # $4 / $20 / $5 / $0.20 per million tokens for input, output, cache writes, cache reads
    assert run.cost_usd == pytest.approx((3000 * 4 + 1500 * 20 + 3000 * 5 + 6000 * 0.2) / 1_000_000)


def test_a_bad_document_id_is_reported_to_the_model_not_raised(store, cases, truths):
    case, truth = a_case(cases, truths)
    api = ScriptedAPI([tool_turn(("read_document", {"document_id": "DOC-9999"})), *search_read_answer(store, case, truth)])
    run = ClaudeExtractor(store, api).extract(case)

    error_result = api.requests[1]["messages"][2]["content"][0]
    assert error_result["is_error"] is True and "DOC-9999" in error_result["content"]
    assert run.error is None


def test_a_refusal_sends_the_case_to_a_person(store, cases, truths):
    case, _ = a_case(cases, truths)
    refusal = response([], "refusal", stop_details={"type": "refusal", "category": "cyber", "explanation": "..."})

    result = vouch(case, ClaudeExtractor(store, ScriptedAPI([refusal])), store)

    assert result.run.error == "refused (cyber)"
    assert result.report.status == "NEEDS_REVIEW"  # not MISSING_EVIDENCE: nothing was shown to be missing


def test_the_loop_gives_up_after_the_turn_limit(store, cases, truths):
    case, _ = a_case(cases, truths)
    endless = [tool_turn(("search_documents", {"query": "invoice"})) for _ in range(MAX_TURNS)]
    run = ClaudeExtractor(store, ScriptedAPI(endless)).extract(case)
    assert run.error == f"no answer after {MAX_TURNS} turns"


def test_an_answer_that_is_not_valid_json_is_an_error(store, cases, truths):
    case, _ = a_case(cases, truths)
    broken = response([thinking(), {"type": "text", "text": "not json"}], "end_turn")
    run = ClaudeExtractor(store, ScriptedAPI([broken])).extract(case)
    assert run.error.startswith("unusable answer")


def test_record_then_replay_gives_the_same_run_without_the_api(store, cases, truths, tmp_path):
    case, truth = a_case(cases, truths)
    recorded = ClaudeExtractor(store, RecordingAPI(ScriptedAPI(search_read_answer(store, case, truth)), tmp_path))
    first = recorded.extract(case)
    assert len(list(tmp_path.glob("*.json"))) == 3  # one file per request

    replayed = ClaudeExtractor(store, ReplayAPI(tmp_path)).extract(case)

    assert replayed.extraction == first.extraction
    assert replayed.tool_calls == first.tool_calls
    assert replayed.cost_usd == first.cost_usd


def test_replay_without_a_recording_says_so(store, cases, truths, tmp_path):
    case, _ = a_case(cases, truths)
    with pytest.raises(MissingRecording, match="record it first"):
        ClaudeExtractor(store, ReplayAPI(tmp_path)).extract(case)


def test_the_output_schema_is_strict_everywhere():
    schema = strict_json_schema(Extraction)

    def objects(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                yield node
            for value in node.values():
                yield from objects(value)
        elif isinstance(node, list):
            for item in node:
                yield from objects(item)

    assert "$ref" not in str(schema) and "$defs" not in schema
    for node in objects(schema):
        assert node["additionalProperties"] is False
        assert node["required"] == list(node["properties"])
    assert "TAX_ADVISORY" in str(schema)
