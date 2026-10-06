"""The client's evidence store, and the two tools the agent uses on it.

    search_documents(query)   keyword search over every document; returns the best matches
    read_document(id)         the full text, page by page, so quotes can name their page

Both are ordinary, deterministic code: the model decides what to look for,
but finding and reading documents never depends on the model.
"""

import csv
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from app.domain import Case, Document, GroundTruth, PaidInvoice, Vendor

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "evidence"
WORD = re.compile(r"[a-z0-9]+")


def words(text: str) -> list[str]:
    return WORD.findall(text.lower())


@dataclass(frozen=True)
class SearchHit:
    document_id: str
    document_type: str
    vendor_name: str
    title: str
    snippet: str  # the line that best matches the query
    score: float


class UnknownDocument(KeyError):
    pass


class EvidenceStore:
    def __init__(self, documents: list[Document], vendors: list[Vendor], paid_invoices: list[PaidInvoice]):
        self.documents = {document.document_id: document for document in documents}
        self.vendors = vendors
        self.paid_invoices = paid_invoices
        # For each document, how often each word appears; for scoring, how many documents contain each word.
        self._word_counts = {
            document.document_id: Counter(words(" ".join([document.title, document.vendor_name, *document.pages])))
            for document in documents
        }
        document_frequency = Counter(word for counts in self._word_counts.values() for word in counts)
        total = len(documents)
        # Rare words (an invoice number) count for much more than common ones ("invoice").
        self._weight = {word: math.log((total + 1) / (count + 0.5)) for word, count in document_frequency.items()}

    @classmethod
    def load(cls, directory: Path = DATA_DIR) -> "EvidenceStore":
        documents = [Document.model_validate_json(line) for line in _lines(directory / "documents.jsonl")]
        vendors = [Vendor.model_validate(row) for row in _csv(directory / "vendors.csv")]
        paid = [PaidInvoice.model_validate(row) for row in _csv(directory / "paid_invoices.csv")]
        return cls(documents, vendors, paid)

    def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        query_words = set(words(query))
        scored = []
        for document_id, counts in self._word_counts.items():
            # Each matching word adds its weight; repeating a word helps a little, up to three times.
            score = sum(self._weight[w] * min(counts[w], 3) for w in query_words if w in counts)
            if score > 0:
                scored.append((score, document_id))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [self._hit(document_id, query_words, score) for score, document_id in scored[:limit]]

    def read(self, document_id: str) -> str:
        document = self.documents.get(document_id)
        if document is None:
            raise UnknownDocument(document_id)
        header = f"{document.document_id} | {document.document_type} | {document.title}"
        pages = [f"[page {number}]\n{text}" for number, text in enumerate(document.pages, start=1)]
        return "\n".join([header, *pages])

    def page_text(self, document_id: str, page: int) -> str | None:
        document = self.documents.get(document_id)
        if document is None or not 1 <= page <= len(document.pages):
            return None
        return document.pages[page - 1]

    def _hit(self, document_id: str, query_words: set[str], score: float) -> SearchHit:
        document = self.documents[document_id]
        lines = [line for page in document.pages for line in page.splitlines() if line.strip()]
        best_line = max(lines, key=lambda line: len(query_words & set(words(line))))
        return SearchHit(
            document_id=document_id,
            document_type=str(document.document_type),
            vendor_name=document.vendor_name,
            title=document.title,
            snippet=best_line[:160],
            score=round(score, 2),
        )


def load_cases(directory: Path = DATA_DIR) -> list[Case]:
    return [Case.model_validate_json(line) for line in _lines(directory / "cases.jsonl")]


def load_ground_truth(directory: Path = DATA_DIR) -> dict[str, GroundTruth]:
    truths = [GroundTruth.model_validate_json(line) for line in _lines(directory / "ground_truth.jsonl")]
    return {truth.case_id: truth for truth in truths}


def _lines(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def hits_as_json(hits: list[SearchHit]) -> str:
    """What the model sees as the search tool's result."""
    return json.dumps([hit.__dict__ for hit in hits], indent=1)
