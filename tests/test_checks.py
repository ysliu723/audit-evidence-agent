"""The eight checks: code, not the model, decides; a value is used only after its citation holds up."""

import pytest

from app.checks import CHECK_CODES, run_checks
from evaluation.oracle import oracle_findings
from tests.helpers import case_for, cases, store, truths


def check(scenario: str, change=None, layouts: str = "AB"):
    case, truth = case_for(scenario, layouts)
    findings = oracle_findings(case, truth)
    if change:
        change(findings)
    return run_checks(case, findings, store().folder(case), store()), truth


def test_with_perfect_reading_every_label_is_reproduced():
    wrong = []
    for case_id, case in cases().items():
        truth = truths()[case_id]
        report = run_checks(case, oracle_findings(case, truth), store().folder(case), store())
        wrong += [(case_id, c) for c in CHECK_CODES if report.verdicts[c] != truth.expected[c]]
    assert wrong == []


def test_a_supported_case_passes_every_check_with_its_sources():
    report, _ = check("supported")
    assert report.status == "SUPPORTED" and set(report.verdicts.values()) == {"PASS"}
    assert report.finding("ARITHMETIC").sources and report.finding("APPROVAL").sources


@pytest.mark.parametrize("scenario, failing, words", [
    ("lookalike_vendor", "VENDOR_IDENTITY", "closely resembles approved vendor"),
    ("changed_bank", "VENDOR_IDENTITY", "differs from the account on file"),
    ("wrong_po", "DOCUMENT_LINKS", "but the purchase order is"),
    ("missing_receipt", "QUANTITY", "no receiving record"),
    ("over_quantity", "QUANTITY", "received"),
    ("price_above_po", "UNIT_PRICE", "the purchase order price is"),
    ("arithmetic_error", "ARITHMETIC", "but the line says"),
    ("amount_mismatch", "ARITHMETIC", "is not the entry's amount"),
    ("cutoff", "DATES", "after the fiscal year end"),
    ("po_after_invoice", "DATES", "invoiced before they were ordered"),
    ("over_limit", "APPROVAL", "above Dana Whitfield's approval limit"),
    ("self_approved", "APPROVAL", "also prepared the entry"),
    ("duplicate", "DUPLICATES", "was already paid by entry"),
])
def test_each_exception_fails_its_check_and_says_why(scenario, failing, words):
    report, _ = check(scenario)
    assert report.status == "EXCEPTION" and failing in report.failures
    assert words in report.finding(failing).detail


def test_contract_term_is_checked_when_the_vendor_has_a_contract():
    report, _ = check("contract_expired")
    assert report.failures == ["DATES"] and "outside the contract term" in report.finding("DATES").detail


def test_a_scanned_invoice_sends_every_check_that_needs_it_to_a_person():
    report, _ = check("scanned")
    assert report.status == "NEEDS_REVIEW" and report.failures == []
    assert report.verdicts["APPROVAL"] == "PASS"
    assert {v for c, v in report.verdicts.items() if c != "APPROVAL"} == {"UNABLE"}


def test_reading_the_subtotal_as_the_total_is_caught_by_the_label_not_reported_as_a_mismatch():
    def subtotal_as_total(findings):
        findings.invoice.total_due = findings.invoice.subtotal.model_copy()

    report, _ = check("subtotal_trap", subtotal_as_total)
    arithmetic = report.finding("ARITHMETIC")
    assert arithmetic.status == "UNABLE" and "not labeled as the total due" in arithmetic.detail


def test_a_value_whose_quote_does_not_hold_up_is_not_used():
    def invent_a_price(findings):
        findings.invoice.lines[0].unit_price.value = "1.00"

    report, _ = check("supported", invent_a_price)
    assert report.verdicts["UNIT_PRICE"] == "UNABLE" and report.verdicts["ARITHMETIC"] == "UNABLE"
    assert report.status == "NEEDS_REVIEW"


def test_an_injection_attempt_is_flagged_and_does_not_change_the_result():
    report, truth = check("injection")
    assert report.failures == ["UNIT_PRICE"] and report.flags == ("INSTRUCTIONS_IN_DOCUMENT",)


def test_a_document_from_outside_the_folder_counts_as_not_read():
    case, truth = case_for("supported")
    other = next(c for c in cases().values() if c.case_id != case.case_id)
    findings = oracle_findings(case, truth)
    findings.invoice.document_id = other.documents[0].document_id
    report = run_checks(case, findings, store().folder(case), store())
    assert report.verdicts["VENDOR_IDENTITY"] == "UNABLE"
