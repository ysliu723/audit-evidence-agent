import json

import pytest

from app.checks import Status
from app.evidence import EvidenceStore, load_cases, load_ground_truth
from app.extractors.rules import RuleBasedExtractor
from app.memo import draft_memo, render, template_memo, unsupported_figures
from app.pipeline import vouch
from tests.scripted import ScriptedAPI, response, thinking


@pytest.fixture(scope="module")
def results():
    store = EvidenceStore.load()
    extractor = RuleBasedExtractor(store)
    truths = load_ground_truth()
    by_scenario = {}
    for case in load_cases():
        truth = truths[case.case_id]
        if truth.template in ("A", "B") or truth.template is None:  # layouts the rules can read
            by_scenario.setdefault(truth.scenario, vouch(case, extractor, store))
    return by_scenario


def drafted(text_fields: dict) -> dict:
    return response([thinking(), {"type": "text", "text": json.dumps(text_fields)}], "end_turn")


class TestTemplateMemo:
    def test_a_supported_entry_needs_only_sign_off(self, results):
        memo = template_memo(results["SUPPORTED"])
        assert memo.status == "SUPPORTED" and memo.findings == []
        assert memo.next_steps == ["No follow-up needed beyond reviewer sign-off."]

    @pytest.mark.parametrize(
        "scenario, step",
        [
            ("BANK_ACCOUNT_CHANGED", "contact details on file"),
            ("LOOKALIKE_VENDOR", "Confirm the vendor exists"),
            ("CUTOFF", "after year end"),
            ("MISSING_DOCUMENT", "Request the supporting invoice"),
            ("PROMPT_INJECTION", "Treat the invoice as suspect"),
        ],
    )
    def test_each_exception_gets_its_next_step(self, results, scenario, step):
        memo = template_memo(results[scenario])
        assert any(step in s for s in memo.next_steps)
        assert all(f.status != str(Status.PASS) for f in memo.findings)

    def test_rendering_shows_sources_and_sign_off(self, results):
        text = render(template_memo(results["AMOUNT_MISMATCH"]))
        assert "requires reviewer sign-off" in text and "Source: DOC-" in text


class TestDraftedMemo:
    def test_a_grounded_draft_is_used(self, results):
        result = results["AMOUNT_MISMATCH"]
        detail = result.report.finding("AMOUNT_MATCH").detail  # contains only figures from the facts
        api = ScriptedAPI([drafted({
            "summary": "The invoice total differs from the entry.",
            "explanations": [{"check": "AMOUNT_MATCH", "explanation": detail}],
            "next_steps": ["Ask the vendor for a corrected invoice."],
        })])

        memo = draft_memo(result, api)

        assert memo.drafted_by == "claude-opus-5-5" and memo.warnings == []
        assert memo.summary == "The invoice total differs from the entry."
        request = api.requests[0]
        assert request["output_config"]["effort"] == "low"
        assert request["output_config"]["format"]["type"] == "json_schema"
        assert result.case.entry.entry_id in request["messages"][0]["content"]

    def test_a_draft_with_an_invented_amount_is_discarded(self, results):
        result = results["AMOUNT_MISMATCH"]
        api = ScriptedAPI([drafted({
            "summary": "The vendor overbilled by 12,345.67.",  # not in the evidence
            "explanations": [{"check": "AMOUNT_MATCH", "explanation": "See summary."}],
            "next_steps": [],
        })])

        memo = draft_memo(result, api)

        assert memo.drafted_by == "template"
        assert "12,345.67" in memo.warnings[0]
        assert memo.summary == template_memo(result).summary

    def test_a_draft_that_skips_a_finding_keeps_the_standard_wording(self, results):
        result = results["PROMPT_INJECTION"]
        api = ScriptedAPI([drafted({
            "summary": "The invoice needs follow-up.",
            "explanations": [{"check": "DOCUMENT_INTEGRITY", "explanation": "The invoice addresses automated reviewers."},
                             {"check": "CUTOFF", "explanation": "Nothing to see."}],
            "next_steps": ["Confirm with the vendor."],
        })])

        memo = draft_memo(result, api)

        assert any("did not explain AMOUNT_MATCH" in w for w in memo.warnings)
        assert any("had no issue (CUTOFF)" in w for w in memo.warnings)
        amount = next(f for f in memo.findings if f.check == "AMOUNT_MATCH")
        assert amount.explanation == result.report.finding("AMOUNT_MATCH").detail

    def test_a_refused_draft_falls_back_to_the_template(self, results):
        memo = draft_memo(results["CUTOFF"], ScriptedAPI([response([], "refusal")]))
        assert memo.drafted_by == "template" and "did not finish (refusal)" in memo.warnings[0]

    def test_nothing_to_explain_means_no_model_call(self, results):
        api = ScriptedAPI([])
        memo = draft_memo(results["SUPPORTED"], api)
        assert api.requests == [] and memo.drafted_by == "template"


def test_unsupported_figures_spots_amounts_dates_and_identifiers():
    facts = '{"amount": "57,503.29", "date": "2026-11-14", "invoice": "NA-1062", "doc": "DOC-0042"}'
    text = "Invoice NA-1062 (DOC-0042) for 57,503.29 dated November 14, 2026; also NA-9999 for 10.00 on 2027-01-01."
    assert unsupported_figures(text, facts) == ["10.00", "2027-01-01", "NA-9999"]
