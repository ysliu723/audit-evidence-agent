"""The checks an auditor makes when vouching an entry, done by code, not by the model.

    SUPPORTING_DOCUMENT  an invoice supporting the entry was found
    DOCUMENT_INTEGRITY   the invoice does not try to instruct its reviewer
    AMOUNT_MATCH         the invoice total equals the entry amount
    CUTOFF               an expense posted to this fiscal year is not invoiced after year end
    VENDOR_APPROVED      the vendor is in the approved vendor master (and is not a look-alike)
    BANK_ACCOUNT         the remit-to account matches the one on file
    DUPLICATE_INVOICE    the invoice was not already paid by another entry
    CONTRACT_SCOPE       the services are covered by the vendor's contract, within its limit

Each check returns PASS, FAIL, UNABLE (the information needed could not be
verified, so a person must look), or NOT_APPLICABLE.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher
from enum import StrEnum

from app.citations import citation_problem
from app.domain import Case, Vendor
from app.evidence import EvidenceStore
from app.extraction import Cited, Extraction
from app.integrity import suspicious_lines
from app.parsing import normalize_name

LOOKALIKE_SIMILARITY = 0.8


class Status(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNABLE = "UNABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class Finding:
    check: str
    status: Status
    detail: str
    sources: tuple[str, ...] = ()  # "DOC-0042 p.1: Total Due: $57,503.29"


@dataclass(frozen=True)
class CheckReport:
    findings: tuple[Finding, ...]
    status: str  # SUPPORTED, EXCEPTION, NEEDS_REVIEW, or MISSING_EVIDENCE

    @property
    def failures(self) -> list[str]:
        return [f.check for f in self.findings if f.status == Status.FAIL]

    def finding(self, check: str) -> Finding:
        return next(f for f in self.findings if f.check == check)


class _Verified:
    """The extracted values whose citations held up; anything else is None."""

    def __init__(self, store: EvidenceStore, document_id: str):
        self.store = store
        self.document_id = document_id
        self.problems: dict[str, str] = {}

    def get(self, name: str, cited: Cited | None, kind: str = "text") -> str | None:
        if cited is None:
            return None
        problem = citation_problem(self.store, self.document_id, cited, kind)
        if problem:
            self.problems[name] = problem
            return None
        return cited.value

    def source(self, cited: Cited) -> str:
        return f"{self.document_id} p.{cited.page}: {cited.quote.strip()}"


def run_checks(case: Case, extraction: Extraction, store: EvidenceStore) -> CheckReport:
    entry = case.entry
    invoice = extraction.invoice
    if invoice is None or invoice.document_id not in store.documents:
        missing = Finding("SUPPORTING_DOCUMENT", Status.FAIL, "No invoice supporting this entry was found.")
        return CheckReport((missing,), "MISSING_EVIDENCE")

    v = _Verified(store, invoice.document_id)
    vendor_name = v.get("vendor_name", invoice.vendor_name)
    number = v.get("invoice_number", invoice.invoice_number)
    invoice_date = v.get("invoice_date", invoice.invoice_date, "date")
    total = v.get("total_amount", invoice.total_amount, "amount")
    bank = v.get("bank_last4", invoice.bank_last4)
    findings = [
        Finding("SUPPORTING_DOCUMENT", Status.PASS, f"Invoice {invoice.invoice_number.value} ({invoice.document_id}).",
                (v.source(invoice.invoice_number),)),
        _integrity(store, invoice.document_id),
        _amount(entry.amount, total, v, invoice.total_amount),
        _cutoff(entry.posting_date, case.fiscal_year_end, invoice_date, v, invoice.invoice_date),
    ]
    vendor = _approved_vendor(store.vendors, vendor_name)
    findings.append(_vendor(vendor_name, vendor, store.vendors, v, invoice.vendor_name))
    findings.append(_bank(vendor, bank, v, invoice.bank_last4))
    findings.append(_duplicate(store, entry.entry_id, vendor_name, number, v, invoice.invoice_number))
    findings.append(_scope(extraction, store, vendor_name, total, invoice.service_category))
    return CheckReport(tuple(findings), _overall(findings))


def _overall(findings: list[Finding]) -> str:
    statuses = {f.status for f in findings}
    if Status.FAIL in statuses:
        return "EXCEPTION"
    if Status.UNABLE in statuses:
        return "NEEDS_REVIEW"
    return "SUPPORTED"


def _unverified(check: str, field: str, v: _Verified) -> Finding:
    reason = v.problems.get(field, f"no {field.replace('_', ' ')} was extracted")
    return Finding(check, Status.UNABLE, f"The {field.replace('_', ' ')} could not be verified: {reason}.")


def _integrity(store: EvidenceStore, document_id: str) -> Finding:
    lines = suspicious_lines(store.documents[document_id])
    if lines:
        return Finding(
            "DOCUMENT_INTEGRITY", Status.FAIL,
            "The invoice contains text addressed to automated reviewers. A genuine invoice does not; "
            "treat the document as suspect and confirm it with the vendor.",
            tuple(f"{document_id}: {line.strip()}" for line in lines),
        )
    return Finding("DOCUMENT_INTEGRITY", Status.PASS, "No instructions to reviewers found in the invoice.")


def _amount(entry_amount: Decimal, total: str | None, v: _Verified, cited: Cited) -> Finding:
    if total is None:
        return _unverified("AMOUNT_MATCH", "total_amount", v)
    total_amount = Decimal(total)
    if total_amount == entry_amount:
        return Finding("AMOUNT_MATCH", Status.PASS, f"Invoice total {total_amount:,.2f} matches the entry.",
                       (v.source(cited),))
    return Finding(
        "AMOUNT_MATCH", Status.FAIL,
        f"Invoice total {total_amount:,.2f} does not match the entry amount {entry_amount:,.2f} "
        f"(difference {entry_amount - total_amount:,.2f}).",
        (v.source(cited),),
    )


def _cutoff(posted: date, year_end: date, invoice_date: str | None, v: _Verified, cited: Cited) -> Finding:
    if invoice_date is None:
        return _unverified("CUTOFF", "invoice_date", v)
    issued = date.fromisoformat(invoice_date)
    if posted <= year_end < issued:
        return Finding(
            "CUTOFF", Status.FAIL,
            f"The invoice is dated {issued}, after the fiscal year end {year_end}, but the entry was posted "
            f"to {posted}. The expense may belong to the next fiscal year.",
            (v.source(cited),),
        )
    return Finding("CUTOFF", Status.PASS, f"Invoice dated {issued}, consistent with posting on {posted}.",
                   (v.source(cited),))


def _approved_vendor(vendors: list[Vendor], name: str | None) -> Vendor | None:
    if name is None:
        return None
    return next((vendor for vendor in vendors if normalize_name(vendor.name) == normalize_name(name)), None)


def _vendor(name: str | None, vendor: Vendor | None, vendors: list[Vendor], v: _Verified, cited: Cited) -> Finding:
    if name is None:
        return _unverified("VENDOR_APPROVED", "vendor_name", v)
    if vendor is not None:
        return Finding("VENDOR_APPROVED", Status.PASS, f"{name} is approved vendor {vendor.vendor_id}.",
                       (v.source(cited),))
    closest = max(vendors, key=lambda other: _similarity(name, other.name))
    similarity = _similarity(name, closest.name)
    if similarity >= LOOKALIKE_SIMILARITY:
        detail = (
            f"{name} is not an approved vendor, but closely resembles approved vendor {closest.name} "
            f"(similarity {similarity:.2f}). A look-alike name is a common sign of a fictitious vendor."
        )
    else:
        detail = f"{name} is not in the approved vendor master."
    return Finding("VENDOR_APPROVED", Status.FAIL, detail, (v.source(cited),))


def _similarity(first: str, second: str) -> float:
    return SequenceMatcher(None, normalize_name(first), normalize_name(second)).ratio()


def _bank(vendor: Vendor | None, bank: str | None, v: _Verified, cited: Cited | None) -> Finding:
    if vendor is None:
        return Finding("BANK_ACCOUNT", Status.NOT_APPLICABLE, "No approved vendor to compare the bank account with.")
    if bank is None:
        return _unverified("BANK_ACCOUNT", "bank_last4", v)
    if bank == vendor.bank_last4:
        return Finding("BANK_ACCOUNT", Status.PASS, f"Remit-to account ending {bank} matches the vendor master.",
                       (v.source(cited),))
    return Finding(
        "BANK_ACCOUNT", Status.FAIL,
        f"Remit-to account ending {bank} differs from the account on file (ending {vendor.bank_last4}). "
        "Confirm the change with the vendor through a known contact before paying: changed bank details "
        "are a common payment-fraud pattern.",
        (v.source(cited),),
    )


def _duplicate(store: EvidenceStore, entry_id: str, vendor_name: str | None, number: str | None, v: _Verified,
               cited: Cited) -> Finding:
    if number is None or vendor_name is None:
        return _unverified("DUPLICATE_INVOICE", "invoice_number" if number is None else "vendor_name", v)
    for paid in store.paid_invoices:
        same = normalize_name(paid.vendor_name) == normalize_name(vendor_name) and paid.invoice_number == number
        if same and paid.paid_by_entry_id != entry_id:
            return Finding(
                "DUPLICATE_INVOICE", Status.FAIL,
                f"Invoice {number} from {vendor_name} was already paid by entry {paid.paid_by_entry_id}.",
                (v.source(cited),),
            )
    return Finding("DUPLICATE_INVOICE", Status.PASS, f"Invoice {number} has not been paid before.")


def _scope(extraction: Extraction, store: EvidenceStore, vendor_name: str | None, total: str | None,
           category) -> Finding:
    contract = extraction.contract
    if contract is None or contract.document_id not in store.documents:
        return Finding("CONTRACT_SCOPE", Status.UNABLE,
                       "No contract with this vendor was found, so the services and the fee limit were not checked.")
    c = _Verified(store, contract.document_id)
    contract_vendor = c.get("vendor_name", contract.vendor_name)
    scope = c.get("scope", contract.scope)
    if contract_vendor is None or scope is None:
        return _unverified("CONTRACT_SCOPE", "vendor_name" if contract_vendor is None else "scope", c)
    if vendor_name is not None and normalize_name(contract_vendor) != normalize_name(vendor_name):
        return Finding("CONTRACT_SCOPE", Status.UNABLE,
                       f"The contract found is with {contract_vendor}, not with the invoice's vendor {vendor_name}.")
    sources = (c.source(contract.scope),)
    if category not in contract.scope_categories:
        return Finding(
            "CONTRACT_SCOPE", Status.FAIL,
            f"The invoice is for {category} services, which the contract with {contract_vendor} does not cover "
            f"({', '.join(contract.scope_categories)}).",
            sources,
        )
    cap = c.get("not_to_exceed", contract.not_to_exceed, "amount")
    if cap is not None and total is not None and Decimal(total) > Decimal(cap):
        return Finding(
            "CONTRACT_SCOPE", Status.FAIL,
            f"The invoice total {Decimal(total):,.2f} exceeds the contract's limit of {Decimal(cap):,.2f}.",
            sources + (c.source(contract.not_to_exceed),),
        )
    return Finding("CONTRACT_SCOPE", Status.PASS, "The services are within the contract's scope and limit.", sources)
