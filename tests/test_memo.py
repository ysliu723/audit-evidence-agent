"""The memo a reviewer signs: standard wording, or a Claude draft that may use only figures from the evidence."""

import json

import pytest

from app.checks import Status
from app.extractors.rules import RuleBasedExtractor
from app.memo import draft_memo, render, template_memo, unsupported_figures
from app.pipeline import vouch
from tests.helpers import case_for, store
from tests.scripted import ScriptedAPI, response, thinking


def result(scenario: str):
    case, _ = case_for(scenario)
    return vouch(case, RuleBasedExtractor(store()), store())


def drafted(text_fields: dict) -> dict:
    return response([thinking(), {"type": "text", "text": json.dumps(text_fields)}], "end_turn")


class TestTemplateMemo:
    def test_a_supported_entry_needs_only_sign_off(self):
        memo = template_memo(result("supported"))
        assert memo.status == "SUPPORTED" and memo.findings == []
        assert memo.next_steps == ["No follow-up needed beyond reviewer sign-off."]

    @pytest.mark.parametrize("scenario, step", [
        ("changed_bank", "contact details on file"),
        ("over_quantity", "proof the billed quantity was received"),
        ("price_above_po", "credit note for the overcharge"),
        ("cutoff", "cut-off adjustment"),
        ("self_approved", "did not prepare the entry"),
        ("duplicate", "paid twice"),
    ])
    def test_each_exception_gets_its_next_step(self, scenario, step):
        memo = template_memo(result(scenario))
        assert any(step in s for s in memo.next_steps)
        assert all(f.status != str(Status.PASS) for f in memo.findings)

    def test_an_injection_attempt_is_raised_with_the_reviewer(self):
        memo = template_memo(result("injection"))
        assert any("addressed to automated reviewers" in w for w in memo.warnings)

    def test_rendering_shows_sources_and_sign_off(self):
        text = render(template_memo(result("amount_mismatch")))
        assert "requires reviewer sign-off" in text and "Source: DOC-" in text


class TestDraftedMemo:
    def test_a_grounded_draft_is_used(self):
        r = result("amount_mismatch")
        detail = r.report.finding("ARITHMETIC").detail  # contains only figures from the facts
        api = ScriptedAPI([drafted({"summary": "The invoice total differs from the entry.",
                                    "explanations": [{"check": "ARITHMETIC", "explanation": detail}],
                                    "next_steps": ["Ask the vendor for a corrected invoice."]})])
        memo = draft_memo(r, api)
        assert memo.drafted_by == "claude-opus-5-5" and memo.warnings == []
        request = api.requests[0]
        assert request["output_config"]["effort"] == "low" and request["output_config"]["format"]["type"] == "json_schema"

    def test_a_draft_with_an_invented_amount_is_discarded(self):
        r = result("amount_mismatch")
        api = ScriptedAPI([drafted({"summary": "The vendor overbilled by 12,345.67.",
                                    "explanations": [{"check": "ARITHMETIC", "explanation": "See summary."}],
                                    "next_steps": []})])
        memo = draft_memo(r, api)
        assert memo.drafted_by == "template" and "12,345.67" in memo.warnings[0]

    def test_a_refused_draft_falls_back_to_the_template(self):
        memo = draft_memo(result("cutoff"), ScriptedAPI([response([], "refusal")]))
        assert memo.drafted_by == "template" and "did not finish (refusal)" in memo.warnings[0]

    def test_nothing_to_explain_means_no_model_call(self):
        api = ScriptedAPI([])
        assert draft_memo(result("supported"), api).drafted_by == "template" and api.requests == []


def test_unsupported_figures_spots_amounts_dates_and_identifiers():
    facts = '{"amount": "57,503.29", "date": "2026-11-14", "invoice": "INV-1062", "doc": "DOC-0042"}'
    text = "Invoice INV-1062 (DOC-0042) for 57,503.29 dated November 14, 2026; also INV-9999 for 10.00 on 2027-01-01."
    assert unsupported_figures(text, facts) == ["10.00", "2027-01-01", "INV-9999"]
