"""The no-AI baseline: templates for the invoice layouts it was written for, and for the client's own forms.

Each template knows a layout's fixed labels ("Invoice No:", "Bill No.", "Amount payable") and reads the
value next to them, line by line, so every value still comes with its page and exact line and goes through
the same citation checks as the model's. It reads the two invoice layouts in the dev cases (A and B) and
the client's purchase orders, receiving reports, and contracts, which always look the same. An invoice in
any other layout gives it nothing to read, so the checks that need the invoice report UNABLE: this is
the problem a model that reads the page solves.
"""

import re
import time

from app.domain import Case, DocumentType
from app.evidence import CaseFolder, EvidenceStore
from app.extraction import (Cited, ContractFindings, Findings, InvoiceFindings, InvoiceLine, PurchaseOrderFindings,
                            PurchaseOrderLine, ReceiptLine, ReceivingFindings)
from app.parsing import all_amounts, all_dates

ROW = re.compile(r"^(?P<description>\S.*?)\s{2,}(?P<quantity>\d+)\s{2,}\$?(?P<unit>[\d,]+\.\d{2})\s{2,}"
                 r"\$?(?P<amount>[\d,]+\.\d{2})$")
RECEIPT_ROW = re.compile(r"^(?P<description>\S.*?)\s{2,}(?P<quantity>\d+)$")
TEMPLATES = {  # field -> the label the layout prints before it
    "A": {"invoice_number": "Invoice No:", "invoice_date": "Invoice Date:", "po_number": "PO Number:",
          "tax_id": "Tax ID:", "subtotal": "Subtotal:", "tax": "Tax (", "total_due": "Total Due:",
          "bank_last4": "Remit to:", "table": "Description"},
    "B": {"invoice_number": "Bill No.", "invoice_date": "Date:", "po_number": "Your order:",
          "tax_id": "Vendor tax ID", "subtotal": "Net amount", "tax": "Sales tax", "total_due": "Amount payable",
          "bank_last4": "Pay to account", "table": "Item"},
}


class Lines:
    """A document's lines with their page numbers."""

    def __init__(self, folder: CaseFolder, document_id: str):
        self.items = [(n, line.strip()) for n, text in enumerate(folder.pages(document_id), start=1)
                      for line in text.splitlines() if line.strip()]

    def starting(self, label: str) -> tuple[int, str] | None:
        return next(((n, line) for n, line in self.items if line.startswith(label)), None)

    def after(self, label: str) -> Cited | None:
        found = self.starting(label)
        if found is None:
            return None
        page, line = found
        return Cited(value=line[len(label):].strip(), page=page, quote=line)


class RuleBasedExtractor:
    name = "rules"

    def __init__(self, store: EvidenceStore):
        self.store = store

    def extract(self, case: Case):
        from app.extractors.base import ExtractionRun

        started = time.perf_counter()
        folder = self.store.folder(case)
        invoices = [self._invoice(folder, d.document_id) for d in folder.of_type(DocumentType.INVOICE)]
        invoices = [i for i in invoices if i is not None]
        findings = Findings(invoice=_choose(invoices, case), purchase_order=self._po(folder),
                            receiving_record=self._receipt(folder), contract=self._contract(folder),
                            notes="" if invoices else "No invoice in a known layout.")
        return ExtractionRun(findings=findings, seconds=time.perf_counter() - started)

    def _invoice(self, folder: CaseFolder, document_id: str) -> InvoiceFindings | None:
        lines = Lines(folder, document_id)
        for layout, labels in TEMPLATES.items():
            number = lines.after(labels["invoice_number"])
            header = lines.starting(labels["table"])
            if number is None or header is None:
                continue
            page_one = [line for n, line in lines.items if n == 1]
            vendor_line = page_one[0] if layout == "A" else page_one[1]
            date = lines.after(labels["invoice_date"])
            dates = all_dates(date.value) if date else []
            rows = [(n, line, ROW.match(line)) for n, line in lines.items]
            items = []
            for n, line, match in rows:
                if match is None:
                    continue
                items.append(InvoiceLine(
                    description=Cited(value=match["description"].strip(), page=n, quote=line),
                    quantity=Cited(value=match["quantity"], page=n, quote=line),
                    unit_price=Cited(value=match["unit"].replace(",", ""), page=n, quote=line),
                    amount=Cited(value=match["amount"].replace(",", ""), page=n, quote=line)))
            bank = lines.after(labels["bank_last4"])
            digits = re.search(r"(\d{4})$", bank.value) if bank else None
            return InvoiceFindings(
                document_id=document_id,
                vendor_name=Cited(value=vendor_line, page=1, quote=vendor_line),
                tax_id=lines.after(labels["tax_id"]),
                invoice_number=number,
                invoice_date=Cited(value=dates[0].isoformat(), page=date.page, quote=date.quote) if dates else
                Cited(value="", page=1, quote=""),
                po_number=lines.after(labels["po_number"]),
                bank_last4=Cited(value=digits.group(1), page=bank.page, quote=bank.quote) if digits else None,
                lines=items,
                subtotal=_amount(lines.after(labels["subtotal"])),
                tax=_amount(lines.after(labels["tax"])),
                total_due=_amount(lines.after(labels["total_due"])) or Cited(value="0", page=1, quote=""),
            )
        return None

    def _po(self, folder: CaseFolder) -> PurchaseOrderFindings | None:
        documents = folder.of_type(DocumentType.PURCHASE_ORDER)
        if not documents:
            return None
        document_id = documents[0].document_id
        lines = Lines(folder, document_id)
        approval = lines.after("Approved by:")
        items = []
        for n, line in lines.items:
            if match := ROW.match(line):
                items.append(PurchaseOrderLine(description=Cited(value=match["description"].strip(), page=n, quote=line),
                                               quantity=Cited(value=match["quantity"], page=n, quote=line),
                                               unit_price=Cited(value=match["unit"].replace(",", ""), page=n,
                                                                quote=line)))
        return PurchaseOrderFindings(
            document_id=document_id, po_number=lines.after("PO Number:"), po_date=_date(lines.after("PO Date:")),
            vendor_name=lines.after("Vendor:"),
            approved_by=Cited(value=approval.value.split(",")[0], page=approval.page, quote=approval.quote),
            lines=items, po_total=_amount(lines.after("PO Total:")))

    def _receipt(self, folder: CaseFolder) -> ReceivingFindings | None:
        documents = folder.of_type(DocumentType.RECEIVING_RECORD)
        if not documents:
            return None
        document_id = documents[0].document_id
        lines = Lines(folder, document_id)
        items = [ReceiptLine(description=Cited(value=m["description"].strip(), page=n, quote=line),
                             quantity_received=Cited(value=m["quantity"], page=n, quote=line))
                 for n, line in lines.items if (m := RECEIPT_ROW.match(line)) and not line.startswith("Item")]
        return ReceivingFindings(document_id=document_id, receipt_number=lines.after("Receipt No:"),
                                 po_number=lines.after("PO Number:"),
                                 received_date=_date(lines.after("Date Received:")), lines=items)

    def _contract(self, folder: CaseFolder) -> ContractFindings | None:
        documents = folder.of_type(DocumentType.CONTRACT)
        if not documents:
            return None
        document_id = documents[0].document_id
        lines = Lines(folder, document_id)
        parties, term = lines.after("Between"), lines.after("Term:")
        vendor = parties.value.split(" and ", 1)[1] if parties else ""
        dates = all_dates(term.value) if term else []
        return ContractFindings(
            document_id=document_id, vendor_name=Cited(value=vendor, page=parties.page, quote=parties.quote),
            term_start=Cited(value=dates[0].isoformat(), page=term.page, quote=term.quote),
            term_end=Cited(value=dates[1].isoformat(), page=term.page, quote=term.quote))


def _choose(invoices: list[InvoiceFindings], case: Case) -> InvoiceFindings | None:
    """The invoice whose number is in the entry's description, else the one whose total is the entry amount."""
    for invoice in invoices:
        if invoice.invoice_number.value in case.entry.description:
            return invoice
    for invoice in invoices:
        if invoice.total_due.value and _equal(invoice.total_due.value, case.entry.amount):
            return invoice
    return invoices[0] if invoices else None


def _equal(text: str, amount) -> bool:
    try:
        from decimal import Decimal

        return Decimal(text) == amount
    except ArithmeticError:
        return False


def _amount(cited: Cited | None) -> Cited | None:
    if cited is None:
        return None
    amounts = all_amounts(cited.quote)
    return Cited(value=str(amounts[-1]), page=cited.page, quote=cited.quote) if amounts else None


def _date(cited: Cited | None) -> Cited | None:
    if cited is None:
        return None
    dates = all_dates(cited.quote)
    return Cited(value=dates[0].isoformat(), page=cited.page, quote=cited.quote) if dates else cited
