"""A perfect extractor that reads the answers from ground truth, for evaluation only.

Running the checks on its output shows what the checks themselves get right
when extraction is flawless. Any mistake a real extractor makes on top of
that comes from extraction, not from the checks.
"""

from app.domain import Case, GroundTruth
from app.evidence import EvidenceStore
from app.extraction import Cited, ContractExtraction, Extraction, InvoiceExtraction
from app.integrity import suspicious_lines
from app.parsing import all_amounts, all_dates, normalize_name
from scripts.generate_cases import SCOPE_TEXT, SERVICES


def oracle_extraction(case: Case, truth: GroundTruth, store: EvidenceStore) -> Extraction:
    if truth.support_document_id is None:
        return Extraction(invoice=None, contract=None, notes="No invoice supporting the entry exists.")
    invoice_id = truth.support_document_id

    def cite(document_id, value, matches, last=False) -> Cited:
        document = store.documents[document_id]
        avoid = set(suspicious_lines(document))
        found = [
            (number, line)
            for number, page in enumerate(document.pages, start=1)
            for line in page.splitlines()
            if line not in avoid and matches(line)
        ]
        page, line = found[-1] if last else found[0]
        return Cited(value=value, page=page, quote=line)

    service_line = next(s for lines in SERVICES.values() for s in lines
                        if s in "\n".join(store.documents[invoice_id].pages))
    invoice = InvoiceExtraction(
        document_id=invoice_id,
        vendor_name=cite(invoice_id, truth.vendor_name,
                         lambda line: normalize_name(truth.vendor_name) in normalize_name(line)),
        invoice_number=cite(invoice_id, truth.invoice_number, lambda line: truth.invoice_number in line),
        invoice_date=cite(invoice_id, truth.invoice_date.isoformat(), lambda line: truth.invoice_date in all_dates(line)),
        total_amount=cite(invoice_id, str(truth.total_amount), lambda line: truth.total_amount in all_amounts(line),
                          last=True),
        bank_last4=cite(invoice_id, truth.bank_last4, lambda line: truth.bank_last4 in line),
        service_description=cite(invoice_id, service_line, lambda line: service_line in line),
        service_category=truth.service_category,
    )

    contract = None
    if truth.contract_document_id:
        contract_id = truth.contract_document_id
        scope = cite(contract_id, "", lambda line: "Scope of services" in line)
        categories = [category for category, text in SCOPE_TEXT.items() if text in scope.quote]
        cap_cite = cite(contract_id, "", lambda line: "shall not exceed" in line)
        cap = all_amounts(cap_cite.quote)[0]
        vendor_line = cite(contract_id, truth.vendor_name,
                           lambda line: normalize_name(truth.vendor_name) in normalize_name(line))
        contract = ContractExtraction(
            document_id=contract_id,
            vendor_name=vendor_line,
            scope=scope.model_copy(update={"value": "Scope of services"}),
            scope_categories=categories,
            not_to_exceed=cap_cite.model_copy(update={"value": str(cap)}),
        )
    return Extraction(invoice=invoice, contract=contract, notes="")
