"""A rule-based extractor with no AI: the baseline Claude has to beat.

The rules were written for the two invoice layouts seen first (A and B), the
way an engineer writes regular expressions for the samples at hand. Layout C,
a letter-style invoice, was deliberately not looked at; the evaluation shows
what happens when rules meet a layout they were not written for.
"""

import re
import time

from app.domain import Case, DocumentType, ServiceCategory
from app.evidence import EvidenceStore
from app.extraction import Cited, ContractExtraction, Extraction, InvoiceExtraction
from app.extractors.base import ExtractionRun
from app.parsing import all_amounts, all_dates, normalize_name

INVOICE_NUMBER_IN_TEXT = re.compile(r"\(([A-Z]{2,3}-\d+)\)")
FIELDS = {
    "vendor_name": [r"^TAX INVOICE - (.+)$"],  # layout A has the vendor on the first line instead (see below)
    "invoice_number": [r"Invoice No\.:\s*(\S+)", r"^Number:\s*(\S+)"],
    "invoice_date": [r"Invoice Date:\s*(.+)$", r"Date of issue:\s*(.+)$"],
    "total_amount": [r"Total Due:\s*(.+)$", r"Amount payable:\s*(.+)$"],
    "bank_last4": [r"account ending (\d{4})"],
    "service_description": [r"^Description:\s*(.+)$", r"^Services rendered:\s*(.+)$"],
}
CATEGORY_KEYWORDS = [
    (ServiceCategory.TAX_ADVISORY, ["tax", "transfer pricing"]),
    (ServiceCategory.IT_CONSULTING, ["erp", "cloud", "data platform", "information technology", "systems"]),
    (ServiceCategory.MARKETING, ["campaign", "market research", "launch", "brand", "marketing", "advertising"]),
    (ServiceCategory.LEGAL, ["contract review", "litigation", "regulatory", "legal"]),
    (ServiceCategory.OTHER, ["maintenance", "cleaning", "security", "facilities"]),
]


def categories_in(text: str) -> list[ServiceCategory]:
    lowered = text.lower()
    return [category for category, keywords in CATEGORY_KEYWORDS if any(k in lowered for k in keywords)]


class RuleBasedExtractor:
    name = "rules"

    def __init__(self, store: EvidenceStore):
        self.store = store

    def extract(self, case: Case) -> ExtractionRun:
        started = time.perf_counter()
        calls = []
        invoice = self._find_invoice(case, calls)
        contract = self._find_contract(invoice.vendor_name.value if invoice else case.entry.vendor, calls)
        notes = "" if invoice else "No invoice matching the entry's number or amount was found."
        extraction = Extraction(invoice=invoice, contract=contract, notes=notes)
        return ExtractionRun(extraction=extraction, tool_calls=calls, seconds=time.perf_counter() - started)

    def _search(self, query: str, calls: list[dict]):
        calls.append({"tool": "search_documents", "input": {"query": query}})
        return self.store.search(query)

    def _find_invoice(self, case: Case, calls: list[dict]) -> InvoiceExtraction | None:
        entry = case.entry
        number = INVOICE_NUMBER_IN_TEXT.search(entry.description)
        if number:
            # Search can return other invoices with similar numbers: accept only the exact number.
            for hit in self._search(number.group(1), calls):
                if hit.document_type == DocumentType.INVOICE:
                    invoice = self._read_invoice(hit.document_id)
                    if invoice.invoice_number.value == number.group(1):
                        return invoice
            return None
        # No invoice number: take the vendor's invoice whose total equals the entry amount.
        for hit in self._search(f"{entry.vendor} {entry.amount:,.2f}", calls):
            if hit.document_type != DocumentType.INVOICE:
                continue
            if normalize_name(hit.vendor_name) != normalize_name(entry.vendor):
                continue
            invoice = self._read_invoice(hit.document_id)
            if invoice.total_amount.value == str(entry.amount):
                return invoice
        return None

    def _read_invoice(self, document_id: str) -> InvoiceExtraction:
        document = self.store.documents[document_id]
        found = {name: self._match(document.pages, patterns) for name, patterns in FIELDS.items()}
        if found["vendor_name"] is None:  # layout A: the vendor's name is the first line
            first_line = document.pages[0].splitlines()[0]
            found["vendor_name"] = (first_line, 1, first_line)
        date_hit, total_hit = found["invoice_date"], found["total_amount"]
        if date_hit:
            dates = all_dates(date_hit[0])
            found["invoice_date"] = (dates[0].isoformat(), date_hit[1], date_hit[2]) if dates else None
        if total_hit:
            amounts = all_amounts(total_hit[0])
            found["total_amount"] = (str(amounts[0]), total_hit[1], total_hit[2]) if amounts else None
        service = found["service_description"]
        categories = categories_in(service[0]) if service else []
        return InvoiceExtraction(
            document_id=document_id,
            vendor_name=self._cited(found["vendor_name"]),
            invoice_number=self._cited(found["invoice_number"]),
            invoice_date=self._cited(found["invoice_date"]),
            total_amount=self._cited(found["total_amount"]),
            bank_last4=self._cited(found["bank_last4"]) if found["bank_last4"] else None,
            service_description=self._cited(service),
            service_category=categories[0] if categories else ServiceCategory.OTHER,
        )

    def _find_contract(self, vendor_name: str, calls: list[dict]) -> ContractExtraction | None:
        for hit in self._search(f"{vendor_name} master services agreement", calls):
            if hit.document_type != DocumentType.CONTRACT:
                continue
            if normalize_name(hit.vendor_name) != normalize_name(vendor_name):
                continue
            document = self.store.documents[hit.document_id]
            scope = self._match(document.pages, [r"(Scope of services\..+)$"])
            cap = self._match(document.pages, [r"(shall not exceed \$[\d,]+\.\d{2})"])
            vendor_line = self._match(document.pages, [r"(Between .+)$"])
            return ContractExtraction(
                document_id=hit.document_id,
                vendor_name=Cited(value=vendor_name, page=vendor_line[1], quote=vendor_line[2]),
                scope=self._cited(scope),
                scope_categories=categories_in(scope[0]) if scope else [],
                not_to_exceed=Cited(value=str(all_amounts(cap[0])[0]), page=cap[1], quote=cap[2]) if cap else None,
            )
        return None

    @staticmethod
    def _match(pages: list[str], patterns: list[str]) -> tuple[str, int, str] | None:
        """The first (value, page, line) any pattern finds, or None."""
        for number, page in enumerate(pages, start=1):
            for line in page.splitlines():
                for pattern in patterns:
                    match = re.search(pattern, line)
                    if match:
                        return match.group(1).strip(), number, line
        return None

    @staticmethod
    def _cited(found: tuple[str, int, str] | None) -> Cited:
        if found is None:
            return Cited(value="", page=1, quote="")  # not found: the checks will report UNABLE
        value, page, line = found
        return Cited(value=value, page=page, quote=line)
