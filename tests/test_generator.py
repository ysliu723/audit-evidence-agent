"""The cases: splits, layouts, folders, and labels."""

from collections import Counter

from app.checks import CHECK_CODES
from app.domain import DocumentType
from tests.helpers import cases, store, truths


def test_eighty_cases_twenty_for_development_and_sixty_held_out():
    splits = Counter(t.split for t in truths().values())
    assert splits == {"dev": 20, "heldout": 60}
    assert sum(len(c.documents) for c in cases().values()) == 298


def test_unseen_layouts_appear_only_in_held_out_cases():
    unseen = [t for t in truths().values() if t.unseen_layout]
    assert len(unseen) == 10 and {t.split for t in unseen} == {"heldout"}
    assert {t.layout for t in truths().values() if t.split == "dev"} == {"A", "B"}
    assert Counter(t.layout for t in unseen) == {"C": 4, "D": 3, "E": 3}


def test_every_folder_has_an_invoice_and_a_purchase_order():
    for case in cases().values():
        types = Counter(d.document_type for d in case.documents)
        assert types[DocumentType.INVOICE] >= 1 and types[DocumentType.PURCHASE_ORDER] == 1
        expect_receipt = truths()[case.case_id].scenario != "missing_receipt"
        assert (types[DocumentType.RECEIVING_RECORD] == 1) == expect_receipt


def test_labels_follow_the_scenario():
    for truth in truths().values():
        assert set(truth.expected) == set(CHECK_CODES)
        if truth.scenario in ("supported", "subtotal_trap", "split_lines"):
            assert set(truth.expected.values()) == {"PASS"}
        if truth.scenario == "scanned":
            assert truth.expected["APPROVAL"] == "PASS"
            assert {v for c, v in truth.expected.items() if c != "APPROVAL"} == {"UNABLE"}


def test_a_scanned_invoice_has_no_text_layer_and_other_pdfs_do():
    for case in cases().values():
        folder = store().folder(case)
        scanned = truths()[case.case_id].scenario == "scanned"
        for document in case.documents:
            pages = folder.pages(document.document_id)
            empty = all(not p for p in pages)
            assert empty == (scanned and document.document_id == truths()[case.case_id].facts["invoice"]["document_id"])


def test_the_subtotal_trap_puts_the_total_on_another_page_than_the_subtotal():
    for truth in truths().values():
        if truth.scenario == "subtotal_trap":
            invoice = truth.facts["invoice"]
            assert invoice["subtotal"]["page"] == 1 and invoice["total_due"]["page"] == 2
