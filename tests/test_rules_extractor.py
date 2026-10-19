"""The template baseline reads the layouts it was written for, and breaks on the others."""

from app.checks import CHECK_CODES
from app.extractors.rules import RuleBasedExtractor
from app.pipeline import vouch
from tests.helpers import case_for, cases, store, truths


def run(case):
    return vouch(case, RuleBasedExtractor(store()), store())


def test_every_dev_case_is_read_correctly():
    wrong = []
    for case_id, truth in truths().items():
        if truth.split == "dev":
            verdicts = run(cases()[case_id]).report.verdicts
            wrong += [(case_id, c) for c in CHECK_CODES if verdicts[c] != truth.expected[c]]
    assert wrong == []


def test_an_unseen_layout_gives_the_templates_nothing_to_read():
    for layouts in ("C", "D"):
        case, _ = case_for("supported" if layouts == "C" else "lookalike_vendor", layouts)
        result = run(case)
        assert result.run.findings.invoice is None
        assert result.report.verdicts["VENDOR_IDENTITY"] == "UNABLE" and result.report.status == "NEEDS_REVIEW"


def test_it_picks_the_invoice_for_this_entry_when_the_folder_has_two():
    for case_id, case in cases().items():
        invoices = [d for d in case.documents if d.document_type == "INVOICE"]
        truth = truths()[case_id]
        if len(invoices) == 2 and truth.layout in "AB" and truth.facts["invoice_readable"]:
            assert run(case).run.findings.invoice.document_id == truth.facts["invoice"]["document_id"]
            return
    raise AssertionError("no case with two invoices")
