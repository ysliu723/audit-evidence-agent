"""The eight checks an auditor makes when vouching an entry, done by code, not by the model.

    VENDOR_IDENTITY  the invoice's vendor is in the vendor master (not a look-alike), with its tax ID and bank account
    DOCUMENT_LINKS   the invoice cites the purchase order, and the receiving record is for that order
    QUANTITY         nothing is billed beyond what was ordered and received
    UNIT_PRICE       every unit price is the purchase order's price
    ARITHMETIC       lines, subtotal, tax, and total add up, and the total due is the entry's amount
    DATES            ordered before invoiced, received within the year the entry is in, within the contract term
    APPROVAL         the order was approved by someone with authority for its amount, who did not prepare the entry
    DUPLICATES       the invoice has not already been paid by another entry

Each check returns PASS, FAIL, or UNABLE: UNABLE means the evidence it needs could not be verified (a
scanned page, a citation that did not hold up), so a person must look. Values reach the checks only after
their citations pass (citations.py), and amounts are exact Decimals.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher
from enum import StrEnum

from app.citations import citation_problem
from app.domain import Case, DocumentType, Vendor
from app.evidence import CaseFolder, EvidenceStore
from app.extraction import Cited, Findings
from app.integrity import instructions_anywhere
from app.parsing import normalize_name

LOOKALIKE_SIMILARITY = 0.8
CHECK_CODES = ["VENDOR_IDENTITY", "DOCUMENT_LINKS", "QUANTITY", "UNIT_PRICE", "ARITHMETIC", "DATES", "APPROVAL",
               "DUPLICATES"]


class Status(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNABLE = "UNABLE"


@dataclass(frozen=True)
class Finding:
    check: str
    status: Status
    detail: str
    sources: tuple[str, ...] = ()  # "DOC-0042 p.1: Total Due: USD 57,503.29"


@dataclass(frozen=True)
class CheckReport:
    findings: tuple[Finding, ...]
    status: str  # SUPPORTED, EXCEPTION, or NEEDS_REVIEW
    flags: tuple[str, ...] = ()  # e.g. instructions to automated reviewers found in a document

    @property
    def failures(self) -> list[str]:
        return [f.check for f in self.findings if f.status == Status.FAIL]

    @property
    def verdicts(self) -> dict[str, str]:
        return {f.check: str(f.status) for f in self.findings}

    def finding(self, check: str) -> Finding:
        return next(f for f in self.findings if f.check == check)


class Verified:
    """One document's extracted values whose citations held up; anything else is None, with the reason kept."""

    def __init__(self, folder: CaseFolder, document_id: str, label: str):
        self.folder, self.document_id, self.label = folder, document_id, label
        self.problems: dict[str, str] = {}

    def get(self, name: str, cited: Cited | None, kind: str = "text", role: str | None = None):
        if cited is None:
            return None
        problem = citation_problem(self.folder, self.document_id, cited, kind, role)
        if problem:
            self.problems[name] = problem
            return None
        if kind == "amount":
            return Decimal(cited.value)
        if kind == "date":
            return date.fromisoformat(cited.value)
        if kind == "quantity":
            return int(cited.value)
        return cited.value.strip()

    def failed(self, name: str) -> bool:
        return name in self.problems

    def source(self, cited: Cited | None) -> str:
        return f"{self.document_id} p.{cited.page}: {cited.quote.strip()}" if cited else self.document_id


@dataclass
class Line:
    description: str
    quantity: int
    unit_price: Decimal | None = None
    amount: Decimal | None = None
    source: str = ""


def run_checks(case: Case, findings: Findings, folder: CaseFolder, store: EvidenceStore) -> CheckReport:
    c = _Context(case, findings, folder, store)
    results = [c.vendor_identity(), c.document_links(), c.quantity(), c.unit_price(), c.arithmetic(), c.dates(),
               c.approval(), c.duplicates()]
    flags = ("INSTRUCTIONS_IN_DOCUMENT",) if instructions_anywhere(folder) else ()
    statuses = {f.status for f in results}
    status = "EXCEPTION" if Status.FAIL in statuses else "NEEDS_REVIEW" if Status.UNABLE in statuses or flags \
        else "SUPPORTED"
    return CheckReport(tuple(results), status, flags)


class _Context:
    def __init__(self, case: Case, findings: Findings, folder: CaseFolder, store: EvidenceStore):
        self.case, self.entry, self.folder, self.store = case, case.entry, folder, store
        self.has = {t: bool(folder.of_type(t)) for t in DocumentType}
        self.inv = self._usable(findings.invoice, DocumentType.INVOICE)
        self.po = self._usable(findings.purchase_order, DocumentType.PURCHASE_ORDER)
        self.rr = self._usable(findings.receiving_record, DocumentType.RECEIVING_RECORD)
        self.contract = self._usable(findings.contract, DocumentType.CONTRACT)
        self.I = Verified(folder, self.inv.document_id, "invoice") if self.inv else None
        self.P = Verified(folder, self.po.document_id, "purchase order") if self.po else None
        self.R = Verified(folder, self.rr.document_id, "receiving record") if self.rr else None
        self.K = Verified(folder, self.contract.document_id, "contract") if self.contract else None

    def _usable(self, extracted, document_type):
        """The extracted document, if it is a document of that type in this case's folder."""
        if extracted is None:
            return None
        document = self.folder.documents.get(extracted.document_id)
        return extracted if document is not None and document.document_type == document_type else None

    # Shared helpers -------------------------------------------------------------------------------------

    def _unable(self, check: str, what: str, verified: Verified | None = None, names: tuple[str, ...] = ()) -> Finding:
        reasons = [f"{n.replace('_', ' ')}: {verified.problems[n]}" for n in names if verified and n in verified.problems]
        detail = f"Could not verify {what}" + (f" ({'; '.join(reasons)})" if reasons else "") + ". A person must look."
        return Finding(check, Status.UNABLE, detail)

    def _no_invoice(self, check: str) -> Finding:
        if not self.has[DocumentType.INVOICE]:
            return Finding(check, Status.FAIL, "There is no invoice in the case's documents.")
        return Finding(check, Status.UNABLE, "The invoice could not be read (for example, a scanned page with no "
                                             "text). A person must read it.")

    def _invoice_lines(self) -> list[Line] | None:
        lines = []
        for n, line in enumerate(self.inv.lines, start=1):
            description = self.I.get(f"line {n} description", line.description)
            quantity = self.I.get(f"line {n} quantity", line.quantity, "quantity")
            unit = self.I.get(f"line {n} unit price", line.unit_price, "amount")
            amount = self.I.get(f"line {n} amount", line.amount, "amount")
            if None in (description, quantity, unit, amount):
                return None
            lines.append(Line(description, quantity, unit, amount, self.I.source(line.amount)))
        return lines or None

    def _po_lines(self) -> dict[str, Line] | None:
        lines = {}
        for n, line in enumerate(self.po.lines, start=1):
            description = self.P.get(f"line {n} description", line.description)
            quantity = self.P.get(f"line {n} quantity", line.quantity, "quantity")
            unit = self.P.get(f"line {n} unit price", line.unit_price, "amount")
            if None in (description, quantity, unit):
                return None
            lines[normalize_name(description)] = Line(description, quantity, unit, None, self.P.source(line.unit_price))
        return lines or None

    def _received(self) -> dict[str, Line] | None:
        lines = {}
        for n, line in enumerate(self.rr.lines, start=1):
            description = self.R.get(f"line {n} description", line.description)
            quantity = self.R.get(f"line {n} quantity", line.quantity_received, "quantity")
            if None in (description, quantity):
                return None
            lines[normalize_name(description)] = Line(description, quantity, source=self.R.source(line.quantity_received))
        return lines or None

    # The checks -----------------------------------------------------------------------------------------

    def vendor_identity(self) -> Finding:
        check = "VENDOR_IDENTITY"
        if not self.inv:
            return self._no_invoice(check)
        name = self.I.get("vendor_name", self.inv.vendor_name)
        bank = self.I.get("bank_last4", self.inv.bank_last4, "last4")
        tax_id = self.I.get("tax_id", self.inv.tax_id)
        if name is None or bank is None or self.I.failed("tax_id"):
            return self._unable(check, "the vendor's name, tax ID, and bank account on the invoice", self.I,
                                ("vendor_name", "bank_last4", "tax_id"))
        sources = (self.I.source(self.inv.vendor_name), self.I.source(self.inv.bank_last4))
        vendor = _master_vendor(self.store.vendors, name)
        if vendor is None:
            closest = max(self.store.vendors, key=lambda v: _similarity(name, v.name))
            similarity = _similarity(name, closest.name)
            if similarity >= LOOKALIKE_SIMILARITY:
                detail = (f"{name} is not an approved vendor, but closely resembles approved vendor {closest.name} "
                          f"(similarity {similarity:.2f}): a common sign of a fictitious vendor.")
            else:
                detail = f"{name} is not in the approved vendor master."
            return Finding(check, Status.FAIL, detail, sources)
        if tax_id is not None and tax_id != vendor.tax_id:
            return Finding(check, Status.FAIL, f"The invoice's tax ID {tax_id} is not {vendor.name}'s ({vendor.tax_id}).",
                           sources + (self.I.source(self.inv.tax_id),))
        if bank != vendor.bank_last4:
            return Finding(check, Status.FAIL,
                           f"The remit-to account ending {bank} differs from the account on file (ending "
                           f"{vendor.bank_last4}). Confirm the change with the vendor through a known contact before "
                           "paying: changed bank details are a common payment-fraud pattern.", sources)
        return Finding(check, Status.PASS, f"{name} is approved vendor {vendor.vendor_id}; tax ID and bank account match.",
                       sources)

    def document_links(self) -> Finding:
        check = "DOCUMENT_LINKS"
        if not self.has[DocumentType.PURCHASE_ORDER]:
            return Finding(check, Status.FAIL, "There is no purchase order in the case's documents.")
        if not self.has[DocumentType.RECEIVING_RECORD]:
            return Finding(check, Status.FAIL, "There is no receiving record, so nothing shows the goods arrived.")
        if not self.inv:
            return self._no_invoice(check)
        if not self.po or not self.rr:
            return self._unable(check, "the purchase order and receiving record numbers")
        inv_po = self.I.get("po_number", self.inv.po_number)
        po_number = self.P.get("po_number", self.po.po_number)
        rr_po = self.R.get("po_number", self.rr.po_number)
        if self.inv.po_number is None:
            return Finding(check, Status.FAIL, "The invoice does not refer to a purchase order.")
        if None in (inv_po, po_number, rr_po):
            return self._unable(check, "the purchase order numbers", self.I if inv_po is None else
                                self.P if po_number is None else self.R, ("po_number",))
        sources = (self.I.source(self.inv.po_number), self.P.source(self.po.po_number), self.R.source(self.rr.po_number))
        if normalize_name(inv_po) != normalize_name(po_number):
            return Finding(check, Status.FAIL, f"The invoice refers to {inv_po}, but the purchase order is {po_number}.",
                           sources)
        if normalize_name(rr_po) != normalize_name(po_number):
            return Finding(check, Status.FAIL, f"The receiving record is for {rr_po}, not {po_number}.", sources)
        return Finding(check, Status.PASS, f"Invoice, purchase order, and receiving record all refer to {po_number}.",
                       sources)

    def quantity(self) -> Finding:
        check = "QUANTITY"
        if not self.has[DocumentType.RECEIVING_RECORD]:
            return Finding(check, Status.FAIL, "There is no receiving record, so nothing shows the quantities billed "
                                               "were received.")
        if not self.inv:
            return self._no_invoice(check)
        if not self.po or not self.rr:
            return self._unable(check, "the quantities ordered and received")
        lines, ordered, received = self._invoice_lines(), self._po_lines(), self._received()
        if lines is None or ordered is None or received is None:
            source = self.I if lines is None else self.P if ordered is None else self.R
            return self._unable(check, "the line quantities", source, tuple(source.problems))
        for line in lines:
            key = normalize_name(line.description)
            if key not in ordered:
                return Finding(check, Status.FAIL, f"{line.description} is billed but not on the purchase order.",
                               (line.source,))
            if key not in received:
                return Finding(check, Status.FAIL, f"{line.description} is billed but was not received.", (line.source,))
            if line.quantity > received[key].quantity:
                return Finding(check, Status.FAIL,
                               f"{line.quantity} of {line.description} billed, but only {received[key].quantity} "
                               "received.", (line.source, received[key].source))
            if line.quantity > ordered[key].quantity:
                return Finding(check, Status.FAIL, f"{line.quantity} of {line.description} billed, but only "
                               f"{ordered[key].quantity} ordered.", (line.source, ordered[key].source))
        return Finding(check, Status.PASS, f"All {len(lines)} line(s) are within the quantities ordered and received.")

    def unit_price(self) -> Finding:
        check = "UNIT_PRICE"
        if not self.has[DocumentType.PURCHASE_ORDER]:
            return Finding(check, Status.FAIL, "There is no purchase order to compare the prices with.")
        if not self.inv:
            return self._no_invoice(check)
        if not self.po:
            return self._unable(check, "the purchase order's prices")
        lines, ordered = self._invoice_lines(), self._po_lines()
        if lines is None or ordered is None:
            source = self.I if lines is None else self.P
            return self._unable(check, "the unit prices", source, tuple(source.problems))
        for line in lines:
            po_line = ordered.get(normalize_name(line.description))
            if po_line is None:
                return Finding(check, Status.FAIL, f"{line.description} is not on the purchase order.", (line.source,))
            if line.unit_price != po_line.unit_price:
                return Finding(check, Status.FAIL,
                               f"{line.description} is billed at {line.unit_price:,.2f} a unit; the purchase order "
                               f"price is {po_line.unit_price:,.2f}.", (line.source, po_line.source))
        return Finding(check, Status.PASS, "Every unit price is the purchase order's price.")

    def arithmetic(self) -> Finding:
        check = "ARITHMETIC"
        if not self.inv:
            return self._no_invoice(check)
        lines = self._invoice_lines()
        total = self.I.get("total_due", self.inv.total_due, "amount", "total_due")
        subtotal = self.I.get("subtotal", self.inv.subtotal, "amount", "subtotal")
        tax = self.I.get("tax", self.inv.tax, "amount", "tax")
        if lines is None or total is None or self.I.failed("subtotal") or self.I.failed("tax"):
            return self._unable(check, "the invoice's amounts", self.I, tuple(self.I.problems))
        for line in lines:
            if line.quantity * line.unit_price != line.amount:
                return Finding(check, Status.FAIL,
                               f"{line.description}: {line.quantity} x {line.unit_price:,.2f} is "
                               f"{line.quantity * line.unit_price:,.2f}, but the line says {line.amount:,.2f}.",
                               (line.source,))
        lines_total = sum((line.amount for line in lines), Decimal("0"))
        if subtotal is not None and lines_total != subtotal:
            return Finding(check, Status.FAIL, f"The lines add up to {lines_total:,.2f}, but the subtotal is "
                           f"{subtotal:,.2f}.", (self.I.source(self.inv.subtotal),))
        before_tax = subtotal if subtotal is not None else lines_total
        if before_tax + (tax or Decimal("0")) != total:
            return Finding(check, Status.FAIL, f"{before_tax:,.2f} plus tax {tax or 0:,.2f} is not the total due "
                           f"{total:,.2f}.", (self.I.source(self.inv.total_due),))
        if total != self.entry.amount:
            return Finding(check, Status.FAIL, f"The invoice's total due {total:,.2f} is not the entry's amount "
                           f"{self.entry.amount:,.2f} (difference {self.entry.amount - total:,.2f}).",
                           (self.I.source(self.inv.total_due),))
        return Finding(check, Status.PASS, f"Lines, subtotal, tax, and total add up; the total due {total:,.2f} is "
                       "the entry's amount.", (self.I.source(self.inv.total_due),))

    def dates(self) -> Finding:
        check = "DATES"
        if not self.inv:
            return self._no_invoice(check)
        if not self.po:
            return self._unable(check, "the purchase order date")
        invoice_date = self.I.get("invoice_date", self.inv.invoice_date, "date")
        po_date = self.P.get("po_date", self.po.po_date, "date")
        if invoice_date is None or po_date is None:
            source = self.I if invoice_date is None else self.P
            return self._unable(check, "the invoice and order dates", source, ("invoice_date", "po_date"))
        sources = [self.I.source(self.inv.invoice_date), self.P.source(self.po.po_date)]
        if po_date > invoice_date:
            return Finding(check, Status.FAIL, f"The purchase order is dated {po_date}, after the invoice "
                           f"({invoice_date}): the goods were invoiced before they were ordered.", tuple(sources))
        year_end = self.case.fiscal_year_end
        if self.has[DocumentType.RECEIVING_RECORD]:
            if not self.rr:
                return self._unable(check, "the date the goods were received")
            received = self.R.get("received_date", self.rr.received_date, "date")
            if received is None:
                return self._unable(check, "the date the goods were received", self.R, ("received_date",))
            sources.append(self.R.source(self.rr.received_date))
            if self.entry.posting_date <= year_end < received:
                return Finding(check, Status.FAIL,
                               f"The goods were received on {received}, after the fiscal year end {year_end}, but the "
                               f"entry was posted on {self.entry.posting_date}. The expense may belong to the next "
                               "year.", tuple(sources))
        if self.has[DocumentType.CONTRACT]:
            if not self.contract:
                return self._unable(check, "the contract term")
            start = self.K.get("term_start", self.contract.term_start, "date")
            end = self.K.get("term_end", self.contract.term_end, "date")
            if start is None or end is None:
                return self._unable(check, "the contract term", self.K, ("term_start", "term_end"))
            sources.append(self.K.source(self.contract.term_start))
            if not start <= invoice_date <= end:
                return Finding(check, Status.FAIL, f"The invoice is dated {invoice_date}, outside the contract term "
                               f"{start} to {end}.", tuple(sources))
        return Finding(check, Status.PASS, "Ordered before invoiced, received within the year, and within any "
                       "contract term.", tuple(sources))

    def approval(self) -> Finding:
        check = "APPROVAL"
        if not self.has[DocumentType.PURCHASE_ORDER]:
            return Finding(check, Status.FAIL, "There is no purchase order, so there is no approval to check.")
        if not self.po:
            return self._unable(check, "the purchase order's approval")
        approver = self.P.get("approved_by", self.po.approved_by)
        po_total = self.P.get("po_total", self.po.po_total, "amount", "po_total")
        if approver is None or po_total is None:
            return self._unable(check, "who approved the order, and its total", self.P, ("approved_by", "po_total"))
        sources = (self.P.source(self.po.approved_by), self.P.source(self.po.po_total))
        authority = next((a for a in self.store.approvers if normalize_name(a.name) == normalize_name(approver)), None)
        if authority is None:
            return Finding(check, Status.FAIL, f"{approver} is not on the list of authorized approvers.", sources)
        if po_total > authority.limit:
            return Finding(check, Status.FAIL, f"The order total {po_total:,.2f} is above {authority.name}'s approval "
                           f"limit of {authority.limit:,.2f}.", sources)
        if normalize_name(approver) == normalize_name(self.entry.prepared_by):
            return Finding(check, Status.FAIL, f"{approver} approved the purchase order and also prepared the entry "
                           "that pays it: the same person should not do both.", sources)
        return Finding(check, Status.PASS, f"Approved by {authority.name} ({authority.title}), within their limit.",
                       sources)

    def duplicates(self) -> Finding:
        check = "DUPLICATES"
        if not self.inv:
            return self._no_invoice(check)
        number = self.I.get("invoice_number", self.inv.invoice_number)
        vendor = self.I.get("vendor_name", self.inv.vendor_name)
        if number is None or vendor is None:
            return self._unable(check, "the invoice number and vendor", self.I, ("invoice_number", "vendor_name"))
        for paid in self.store.paid_invoices:
            if (normalize_name(paid.vendor_name) == normalize_name(vendor) and paid.invoice_number == number
                    and paid.paid_by_entry_id != self.entry.entry_id):
                return Finding(check, Status.FAIL, f"Invoice {number} from {vendor} was already paid by entry "
                               f"{paid.paid_by_entry_id}.", (self.I.source(self.inv.invoice_number),))
        return Finding(check, Status.PASS, f"Invoice {number} has not been paid before.",
                       (self.I.source(self.inv.invoice_number),))


def _master_vendor(vendors: list[Vendor], name: str) -> Vendor | None:
    return next((v for v in vendors if normalize_name(v.name) == normalize_name(name)), None)


def _similarity(first: str, second: str) -> float:
    return SequenceMatcher(None, normalize_name(first), normalize_name(second)).ratio()
