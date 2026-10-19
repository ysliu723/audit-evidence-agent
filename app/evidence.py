"""The evidence: each case's folder of PDFs, the client's master data, and the agent's tools on a folder.

    list_documents()                  the case's documents: id, type, title, and page count
    search_documents(query)           keyword search over the case's pages; returns the matching lines
    read_page(document_id, page)      one page's text, so every quote can name its page

The tools are deterministic code and reach only the case's own folder: a document id from another case,
or a page that does not exist, is refused, and the refusal is recorded. The model decides what to look
for; finding and reading documents never depends on the model.
"""

import csv
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from app.domain import Approver, Case, DocumentFile, DocumentType, GroundTruth, PaidInvoice, Vendor
from app.pdf import read_pages

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "evidence"
WORD = re.compile(r"[a-z0-9]+")
NO_TEXT = ("[This page has no text layer: it is probably a scanned image, so it cannot be read here. Do not guess "
           "its contents; say in your notes that the page could not be read.]")


def words(text: str) -> list[str]:
    return WORD.findall(text.lower())


class OutOfScope(LookupError):
    """A tool asked for something outside the case's folder."""


@dataclass(frozen=True)
class Hit:
    document_id: str
    page: int
    score: float
    lines: tuple[str, ...]  # the best-matching lines on that page


class CaseFolder:
    """The only documents a case's tools can reach."""

    def __init__(self, case: Case, directory: Path = DATA_DIR):
        self.case = case
        self.directory = directory
        self.documents: dict[str, DocumentFile] = {d.document_id: d for d in case.documents}

    def pages(self, document_id: str) -> tuple[str, ...]:
        document = self.documents.get(document_id)
        if document is None:
            raise OutOfScope(f"{document_id} is not one of this case's documents")
        return read_pages(self.directory / document.file)

    def page_text(self, document_id: str, page: int) -> str | None:
        """The page's text, or None if the page does not exist or is outside the folder."""
        try:
            pages = self.pages(document_id)
        except OutOfScope:
            return None
        return pages[page - 1] if 1 <= page <= len(pages) else None

    def of_type(self, document_type: DocumentType) -> list[DocumentFile]:
        return [d for d in self.case.documents if d.document_type == document_type]

    def list_documents(self) -> list[dict]:
        return [{"document_id": d.document_id, "document_type": str(d.document_type), "title": d.title,
                 "pages": len(self.pages(d.document_id))} for d in self.case.documents]

    def search(self, query: str, limit: int = 5) -> list[Hit]:
        """Pages ranked by how well they match; rare words (an invoice number) count far more than common ones."""
        query_words = set(words(query))
        if not query_words:
            return []
        pages = [(d.document_id, n, text) for d in self.case.documents
                 for n, text in enumerate(self.pages(d.document_id), start=1)]
        counts = {(doc, n): Counter(words(text)) for doc, n, text in pages}
        frequency = Counter(w for c in counts.values() for w in c)
        weight = {w: math.log((len(pages) + 1) / (frequency[w] + 0.5)) for w in query_words}
        scored = []
        for doc, n, text in pages:
            c = counts[(doc, n)]
            score = sum(weight[w] * min(c[w], 3) for w in query_words if w in c)
            if score > 0:
                lines = [line for line in text.splitlines() if line.strip()]
                best = sorted(lines, key=lambda line: -len(query_words & set(words(line))))[:2]
                scored.append(Hit(doc, n, round(score, 2), tuple(line.strip()[:160] for line in best)))
        scored.sort(key=lambda hit: (-hit.score, hit.document_id, hit.page))
        return scored[:limit]

    def read_page(self, document_id: str, page: int) -> str:
        pages = self.pages(document_id)
        if not 1 <= page <= len(pages):
            raise OutOfScope(f"{document_id} has {len(pages)} page(s); there is no page {page}")
        return pages[page - 1] or NO_TEXT


class EvidenceStore:
    """The client's records that code checks against. The model never sees these."""

    def __init__(self, vendors: list[Vendor], approvers: list[Approver], paid_invoices: list[PaidInvoice],
                 directory: Path = DATA_DIR):
        self.vendors, self.approvers, self.paid_invoices = vendors, approvers, paid_invoices
        self.directory = directory

    @classmethod
    def load(cls, directory: Path = DATA_DIR) -> "EvidenceStore":
        return cls([Vendor.model_validate(r) for r in _csv(directory / "vendors.csv")],
                   [Approver.model_validate(r) for r in _csv(directory / "approvers.csv")],
                   [PaidInvoice.model_validate(r) for r in _csv(directory / "paid_invoices.csv")], directory)

    def folder(self, case: Case) -> CaseFolder:
        return CaseFolder(case, self.directory)


def load_cases(directory: Path = DATA_DIR) -> list[Case]:
    return [Case.model_validate_json(line) for line in _lines(directory / "cases.jsonl")]


def load_ground_truth(directory: Path = DATA_DIR) -> dict[str, GroundTruth]:
    truths = [GroundTruth.model_validate_json(line) for line in _lines(directory / "ground_truth.jsonl")]
    return {truth.case_id: truth for truth in truths}


def hits_as_json(hits: list[Hit], snippets: bool = True) -> str:
    """What the model sees as the search result: with snippets it can often skip reading the whole page."""
    return json.dumps([{"document_id": h.document_id, "page": h.page, "score": h.score,
                        **({"lines": list(h.lines)} if snippets else {})} for h in hits], indent=1)


def _lines(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))
