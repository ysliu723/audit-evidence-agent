# Evaluation: rules-dev

Template baseline: fixed labels for layouts A and B, no AI. Split: dev, 20 cases. Run on 2026-10-19.

| Measure | Result |
|---|---|
| Check-level accuracy | **100.0%** (160/160 decisions) |
| Familiar invoice layouts (A, B) | 100.0% (160/160) |
| Unseen invoice layouts (C, D, E) | n/a (0/0) |
| Cases with all eight checks right | 20/20 |
| Wrong abstentions (UNABLE on a clear answer; counted as errors) | 0 |

## By check

| Check | Right |
|---|---|
| VENDOR_IDENTITY | 20/20 |
| DOCUMENT_LINKS | 20/20 |
| QUANTITY | 20/20 |
| UNIT_PRICE | 20/20 |
| ARITHMETIC | 20/20 |
| DATES | 20/20 |
| APPROVAL | 20/20 |
| DUPLICATES | 20/20 |

## By scenario

| Scenario | Cases | Decisions right |
|---|---|---|
| amount_mismatch | 1 | 8/8 |
| arithmetic_error | 1 | 8/8 |
| changed_bank | 1 | 8/8 |
| cutoff | 1 | 8/8 |
| duplicate | 1 | 8/8 |
| injection | 1 | 8/8 |
| lookalike_vendor | 1 | 8/8 |
| missing_receipt | 1 | 8/8 |
| over_limit | 1 | 8/8 |
| over_quantity | 1 | 8/8 |
| po_after_invoice | 1 | 8/8 |
| price_above_po | 1 | 8/8 |
| scanned | 1 | 8/8 |
| self_approved | 1 | 8/8 |
| subtotal_trap | 1 | 8/8 |
| supported | 4 | 32/32 |
| wrong_po | 1 | 8/8 |
