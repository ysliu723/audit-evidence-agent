import pytest

from app.evidence import EvidenceStore, UnknownDocument, load_cases, load_ground_truth


@pytest.fixture(scope="module")
def store():
    return EvidenceStore.load()


@pytest.fixture(scope="module")
def truths():
    return load_ground_truth()


def test_loads_the_committed_data(store):
    assert len(store.documents) == 241
    assert len(store.vendors) == 10
    assert len(load_cases()) == 80


def test_an_invoice_number_finds_its_invoice_first(store, truths):
    for truth in truths.values():
        if truth.invoice_number is None:
            continue
        [best, *_] = store.search(f"{truth.vendor_name} {truth.invoice_number}")
        assert best.document_id == truth.support_document_id


def test_a_vendor_search_returns_that_vendors_documents(store):
    hits = store.search("Northwind Advisory")
    assert hits
    assert all("Northwind" in hit.vendor_name for hit in hits)


def test_hits_show_the_best_matching_line(store, truths):
    truth = next(t for t in truths.values() if t.invoice_number)
    [best, *_] = store.search(truth.invoice_number)
    assert truth.invoice_number in best.snippet


def test_search_results_are_always_in_the_same_order(store):
    assert store.search("consulting invoice") == store.search("consulting invoice")


def test_nothing_matches_nonsense(store):
    assert store.search("zzzz qqqq") == []


def test_read_shows_page_numbers(store, truths):
    truth = next(t for t in truths.values() if t.template == "B")  # a two-page layout
    text = store.read(truth.support_document_id)
    assert text.startswith(f"{truth.support_document_id} | INVOICE")
    assert "[page 1]" in text and "[page 2]" in text
    assert store.page_text(truth.support_document_id, 2).startswith("Summary of charges")
    assert store.page_text(truth.support_document_id, 3) is None


def test_reading_an_unknown_document_fails_clearly(store):
    with pytest.raises(UnknownDocument):
        store.read("DOC-9999")
