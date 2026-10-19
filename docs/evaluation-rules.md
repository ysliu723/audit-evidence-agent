# Evaluation: rules

Template baseline: fixed labels for layouts A and B, no AI. Split: heldout, 60 cases. Run on 2026-10-19.

| Measure | Result |
|---|---|
| Check-level accuracy | **88.5%** (425/480 decisions) |
| Familiar invoice layouts (A, B) | 100.0% (400/400) |
| Unseen invoice layouts (C, D, E) | 31.2% (25/80) |
| Cases with all eight checks right | 50/60 |
| Wrong abstentions (UNABLE on a clear answer; counted as errors) | 55 |

## By check

| Check | Right |
|---|---|
| VENDOR_IDENTITY | 50/60 |
| DOCUMENT_LINKS | 53/60 |
| QUANTITY | 53/60 |
| UNIT_PRICE | 53/60 |
| ARITHMETIC | 50/60 |
| DATES | 53/60 |
| APPROVAL | 60/60 |
| DUPLICATES | 53/60 |

## By scenario

| Scenario | Cases | Decisions right |
|---|---|---|
| amount_mismatch | 2 | 16/16 |
| arithmetic_error | 4 | 30/32 |
| changed_bank | 4 | 25/32 |
| contract_expired | 2 | 16/16 |
| cutoff | 3 | 17/24 |
| duplicate | 4 | 25/32 |
| injection | 4 | 25/32 |
| lookalike_vendor | 4 | 25/32 |
| missing_receipt | 2 | 16/16 |
| over_limit | 2 | 16/16 |
| over_quantity | 4 | 30/32 |
| po_after_invoice | 2 | 16/16 |
| price_above_po | 4 | 25/32 |
| scanned | 2 | 16/16 |
| self_approved | 2 | 16/16 |
| split_lines | 1 | 8/8 |
| subtotal_trap | 2 | 14/16 |
| supported | 10 | 73/80 |
| wrong_po | 2 | 16/16 |

## Wrong decisions

| Case | Scenario | Layout | Check | Expected | Got | Why |
|---|---|---|---|---|---|---|
| CASE-071 | supported | C | VENDOR_IDENTITY | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-071 | supported | C | DOCUMENT_LINKS | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-071 | supported | C | QUANTITY | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-071 | supported | C | UNIT_PRICE | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-071 | supported | C | ARITHMETIC | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-071 | supported | C | DATES | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-071 | supported | C | DUPLICATES | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-072 | lookalike_vendor | D | VENDOR_IDENTITY | FAIL | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-072 | lookalike_vendor | D | DOCUMENT_LINKS | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-072 | lookalike_vendor | D | QUANTITY | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-072 | lookalike_vendor | D | UNIT_PRICE | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-072 | lookalike_vendor | D | ARITHMETIC | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-072 | lookalike_vendor | D | DATES | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-072 | lookalike_vendor | D | DUPLICATES | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-073 | over_quantity | E | VENDOR_IDENTITY | PASS | UNABLE | Could not verify the vendor's name, tax ID, and bank account on the invoice. A person must look. |
| CASE-073 | over_quantity | E | ARITHMETIC | PASS | UNABLE | Could not verify the invoice's amounts (total due: the quote does not appear on page 1 of DOC-0269). A person must look. |
| CASE-074 | price_above_po | C | VENDOR_IDENTITY | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-074 | price_above_po | C | DOCUMENT_LINKS | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-074 | price_above_po | C | QUANTITY | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-074 | price_above_po | C | UNIT_PRICE | FAIL | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-074 | price_above_po | C | ARITHMETIC | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-074 | price_above_po | C | DATES | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-074 | price_above_po | C | DUPLICATES | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-075 | subtotal_trap | E | VENDOR_IDENTITY | PASS | UNABLE | Could not verify the vendor's name, tax ID, and bank account on the invoice. A person must look. |
| CASE-075 | subtotal_trap | E | ARITHMETIC | PASS | UNABLE | Could not verify the invoice's amounts (total due: the quote does not appear on page 1 of DOC-0276). A person must look. |
| CASE-076 | duplicate | D | VENDOR_IDENTITY | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-076 | duplicate | D | DOCUMENT_LINKS | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-076 | duplicate | D | QUANTITY | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-076 | duplicate | D | UNIT_PRICE | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-076 | duplicate | D | ARITHMETIC | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-076 | duplicate | D | DATES | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-076 | duplicate | D | DUPLICATES | FAIL | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-077 | injection | C | VENDOR_IDENTITY | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-077 | injection | C | DOCUMENT_LINKS | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-077 | injection | C | QUANTITY | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-077 | injection | C | UNIT_PRICE | FAIL | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-077 | injection | C | ARITHMETIC | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-077 | injection | C | DATES | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-077 | injection | C | DUPLICATES | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-078 | cutoff | D | VENDOR_IDENTITY | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-078 | cutoff | D | DOCUMENT_LINKS | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-078 | cutoff | D | QUANTITY | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-078 | cutoff | D | UNIT_PRICE | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-078 | cutoff | D | ARITHMETIC | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-078 | cutoff | D | DATES | FAIL | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-078 | cutoff | D | DUPLICATES | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-079 | arithmetic_error | E | VENDOR_IDENTITY | PASS | UNABLE | Could not verify the vendor's name, tax ID, and bank account on the invoice. A person must look. |
| CASE-079 | arithmetic_error | E | ARITHMETIC | FAIL | UNABLE | Could not verify the invoice's amounts (total due: the quote does not appear on page 1 of DOC-0292). A person must look. |
| CASE-080 | changed_bank | C | VENDOR_IDENTITY | FAIL | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-080 | changed_bank | C | DOCUMENT_LINKS | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-080 | changed_bank | C | QUANTITY | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-080 | changed_bank | C | UNIT_PRICE | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-080 | changed_bank | C | ARITHMETIC | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-080 | changed_bank | C | DATES | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
| CASE-080 | changed_bank | C | DUPLICATES | PASS | UNABLE | The invoice could not be read (for example, a scanned page with no text). A person must read it. |
