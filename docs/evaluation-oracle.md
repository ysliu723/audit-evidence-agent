# Evaluation: oracle

Oracle: the true values, read perfectly. Split: all, 80 cases. Run on 2026-10-19.

| Measure | Result |
|---|---|
| Check-level accuracy | **100.0%** (640/640 decisions) |
| Familiar invoice layouts (A, B) | 100.0% (560/560) |
| Unseen invoice layouts (C, D, E) | 100.0% (80/80) |
| Cases with all eight checks right | 80/80 |
| Wrong abstentions (UNABLE on a clear answer; counted as errors) | 0 |

## By check

| Check | Right |
|---|---|
| VENDOR_IDENTITY | 80/80 |
| DOCUMENT_LINKS | 80/80 |
| QUANTITY | 80/80 |
| UNIT_PRICE | 80/80 |
| ARITHMETIC | 80/80 |
| DATES | 80/80 |
| APPROVAL | 80/80 |
| DUPLICATES | 80/80 |

## By scenario

| Scenario | Cases | Decisions right |
|---|---|---|
| amount_mismatch | 3 | 24/24 |
| arithmetic_error | 5 | 40/40 |
| changed_bank | 5 | 40/40 |
| contract_expired | 2 | 16/16 |
| cutoff | 4 | 32/32 |
| duplicate | 5 | 40/40 |
| injection | 5 | 40/40 |
| lookalike_vendor | 5 | 40/40 |
| missing_receipt | 3 | 24/24 |
| over_limit | 3 | 24/24 |
| over_quantity | 5 | 40/40 |
| po_after_invoice | 3 | 24/24 |
| price_above_po | 5 | 40/40 |
| scanned | 3 | 24/24 |
| self_approved | 3 | 24/24 |
| split_lines | 1 | 8/8 |
| subtotal_trap | 3 | 24/24 |
| supported | 14 | 112/112 |
| wrong_po | 3 | 24/24 |
