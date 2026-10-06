import pytest

from app.evidence import EvidenceStore, load_cases, load_ground_truth
from app.extractors.rules import RuleBasedExtractor
from app.pipeline import vouch


@pytest.fixture(scope="module")
def results():
    store = EvidenceStore.load()
    extractor = RuleBasedExtractor(store)
    truths = load_ground_truth()
    return [(vouch(case, extractor, store), truths[case.case_id]) for case in load_cases()]


def test_reads_the_layouts_it_was_written_for(results):
    for result, truth in results:
        if truth.scenario == "SUPPORTED" and truth.template in ("A", "B"):
            invoice = result.run.extraction.invoice
            assert invoice.invoice_number.value == truth.invoice_number
            assert invoice.total_amount.value == str(truth.total_amount)
            assert result.report.status == "SUPPORTED", truth.case_id


def test_cannot_read_the_layout_it_was_not_written_for(results):
    layout_c = [(r, t) for r, t in results if t.scenario == "SUPPORTED" and t.template == "C"]
    assert layout_c
    assert all(r.report.status != "SUPPORTED" for r, _ in layout_c)


def test_is_not_fooled_by_injected_instructions(results):
    for result, truth in results:
        if truth.scenario == "PROMPT_INJECTION" and truth.template in ("A", "B"):
            assert result.run.extraction.invoice.total_amount.value == str(truth.total_amount)


def test_records_the_searches_it_made(results):
    result, _ = results[0]
    assert result.run.tool_calls and result.run.tool_calls[0]["tool"] == "search_documents"
    assert result.run.cost_usd == 0  # no model, no cost
