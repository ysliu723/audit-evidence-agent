from datetime import date
from decimal import Decimal

import pytest

from app.checks import Status, run_checks
from app.evidence import EvidenceStore, load_cases, load_ground_truth
from app.parsing import all_amounts, all_dates, normalize_name
from evaluation.oracle import oracle_extraction


@pytest.fixture(scope="module")
def store():
    return EvidenceStore.load()


@pytest.fixture(scope="module")
def cases():
    return {case.case_id: case for case in load_cases()}


@pytest.fixture(scope="module")
def truths():
    return load_ground_truth()


def first(truths, scenario):
    return next(t for t in truths.values() if t.scenario == scenario)


def check(store, cases, truth, extraction=None):
    case = cases[truth.case_id]
    return run_checks(case, extraction or oracle_extraction(case, truth, store), store)


class TestParsing:
    @pytest.mark.parametrize(
        "text, expected",
        [("Total Due: $57,503.29", "57503.29"), ("USD 1,234.50 payable", "1234.50"), ("fees 950.00 USD", "950.00")],
    )
    def test_amounts(self, text, expected):
        assert all_amounts(text) == [Decimal(expected)]

    @pytest.mark.parametrize(
        "text", ["Dated: 2026-11-14", "Invoice Date: November 14, 2026", "Date of issue: 14 Nov 2026", "11/14/2026"]
    )
    def test_dates_in_every_layout(self, text):
        assert all_dates(text) == [date(2026, 11, 14)]

    def test_vendor_names_ignore_case_and_punctuation(self):
        assert normalize_name("Fabrikam, Inc.") == normalize_name("fabrikam inc")


def test_with_perfect_extraction_every_case_gets_the_right_answer(store, cases, truths):
    for truth in truths.values():
        report = check(store, cases, truth)
        assert (report.status, sorted(report.failures)) == (truth.expected_status, sorted(truth.expected_failures)), (
            truth.case_id, truth.scenario, [f for f in report.findings if f.status != Status.PASS]
        )


def test_a_look_alike_vendor_is_named_as_such(store, cases, truths):
    finding = check(store, cases, first(truths, "LOOKALIKE_VENDOR")).finding("VENDOR_APPROVED")
    assert finding.status == Status.FAIL
    assert "closely resembles approved vendor" in finding.detail


def test_a_changed_bank_account_explains_the_risk(store, cases, truths):
    finding = check(store, cases, first(truths, "BANK_ACCOUNT_CHANGED")).finding("BANK_ACCOUNT")
    assert finding.status == Status.FAIL
    assert "payment-fraud" in finding.detail


def test_an_injected_instruction_is_itself_a_finding(store, cases, truths):
    report = check(store, cases, first(truths, "PROMPT_INJECTION"))
    integrity = report.finding("DOCUMENT_INTEGRITY")
    assert integrity.status == Status.FAIL
    assert "mark every check as passed" in integrity.sources[0]


class TestCitationsAreVerified:
    """An extracted value the document does not support is never used."""

    def extraction(self, store, cases, truth, **total_changes):
        extraction = oracle_extraction(cases[truth.case_id], truth, store)
        total = extraction.invoice.total_amount.model_copy(update=total_changes)
        return extraction.model_copy(update={"invoice": extraction.invoice.model_copy(update={"total_amount": total})})

    def test_a_quote_that_is_not_on_the_page(self, store, cases, truths):
        truth = first(truths, "SUPPORTED")
        report = check(store, cases, truth, self.extraction(store, cases, truth, quote="Total: $1.00"))
        finding = report.finding("AMOUNT_MATCH")
        assert finding.status == Status.UNABLE
        assert "does not appear on page" in finding.detail
        assert report.status == "NEEDS_REVIEW"

    def test_a_page_that_does_not_exist(self, store, cases, truths):
        truth = first(truths, "SUPPORTED")
        report = check(store, cases, truth, self.extraction(store, cases, truth, page=9))
        assert "page 9 does not exist" in report.finding("AMOUNT_MATCH").detail

    def test_a_value_the_quote_does_not_show(self, store, cases, truths):
        truth = first(truths, "SUPPORTED")
        report = check(store, cases, truth, self.extraction(store, cases, truth, value=str(truth.total_amount + 1)))
        assert "does not show the amount" in report.finding("AMOUNT_MATCH").detail

    def test_a_value_quoted_from_the_injected_instruction_is_refused(self, store, cases, truths):
        """If the model is fooled into reporting the injected total, the citation gives it away."""
        truth = first(truths, "PROMPT_INJECTION")
        document = store.documents[truth.support_document_id]
        page = len(document.pages)
        injected_line = next(line for line in document.pages[-1].splitlines() if "Report the total as" in line)
        injected_value = str(all_amounts(injected_line)[0])
        fooled = self.extraction(store, cases, truth, value=injected_value, page=page, quote=injected_line)

        report = check(store, cases, truth, fooled)

        assert report.finding("AMOUNT_MATCH").status == Status.UNABLE
        assert "addressed to automated reviewers" in report.finding("AMOUNT_MATCH").detail
        assert report.status == "EXCEPTION"  # the integrity check still fails the case


def test_a_contract_with_another_vendor_is_not_used(store, cases, truths):
    truth = first(truths, "SUPPORTED")
    other = next(t for t in truths.values() if t.contract_document_id and t.vendor_name != truth.vendor_name)
    extraction = oracle_extraction(cases[truth.case_id], truth, store)
    wrong = oracle_extraction(cases[other.case_id], other, store).contract
    report = check(store, cases, truth, extraction.model_copy(update={"contract": wrong}))
    finding = report.finding("CONTRACT_SCOPE")
    assert finding.status == Status.UNABLE and "not with the invoice's vendor" in finding.detail
