"""The case folder and the tools: only the case's own documents, page by page."""

import json

import pytest

from app.evidence import NO_TEXT, OutOfScope, hits_as_json
from tests.helpers import case_for, cases, store


def test_list_documents_shows_only_the_case_folder():
    case, _ = case_for("supported")
    listed = store().folder(case).list_documents()
    assert [d["document_id"] for d in listed] == [d.document_id for d in case.documents]
    assert all(d["pages"] >= 1 for d in listed)


def test_documents_from_another_case_and_missing_pages_are_refused():
    case, _ = case_for("supported")
    other = next(c for c in cases().values() if c.case_id != case.case_id)
    folder = store().folder(case)
    with pytest.raises(OutOfScope, match="not one of this case's documents"):
        folder.read_page(other.documents[0].document_id, 1)
    with pytest.raises(OutOfScope, match="there is no page 9"):
        folder.read_page(case.documents[0].document_id, 9)
    assert folder.page_text(other.documents[0].document_id, 1) is None


def test_a_scanned_page_says_it_cannot_be_read():
    case, truth = case_for("scanned")
    assert store().folder(case).read_page(truth.facts["invoice"]["document_id"], 1) == NO_TEXT


def test_search_finds_the_invoice_by_its_number_and_returns_the_matching_lines():
    case, truth = case_for("supported")
    number = truth.facts["invoice"]["invoice_number"]["value"]
    hits = store().folder(case).search(number)
    assert hits[0].document_id == truth.facts["invoice"]["document_id"] and hits[0].page == 1
    assert any(number in line for line in hits[0].lines)
    with_snippets, without = json.loads(hits_as_json(hits)), json.loads(hits_as_json(hits, snippets=False))
    assert "lines" in with_snippets[0] and "lines" not in without[0]
