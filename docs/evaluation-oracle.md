# Evaluation: oracle

80 synthetic cases, produced by `python -m evaluation.evaluate --extractor oracle`. A case is correct only if the overall status and the exact set of failed checks both match.

## Headline

| Measure | Result |
|---|---|
| Cases correct | 100% (80/80) |
| Look-alike vendors caught | 100% (8/8) |
| Injected invoices read correctly (not fooled) | 100% (6/6) |
| Supported entries wrongly flagged | 0% (0/24) |
| Citations that hold up | 100% (370/370) |
| Runs that ended in an error | 0 |

## By scenario

| Scenario | Correct |
|---|---|
| AMOUNT_MISMATCH | 100% (10/10) |
| BANK_ACCOUNT_CHANGED | 100% (6/6) |
| CUTOFF | 100% (8/8) |
| DUPLICATE_INVOICE | 100% (6/6) |
| LOOKALIKE_VENDOR | 100% (8/8) |
| MISSING_DOCUMENT | 100% (6/6) |
| OUT_OF_SCOPE | 100% (6/6) |
| PROMPT_INJECTION | 100% (6/6) |
| SUPPORTED | 100% (24/24) |

## By invoice layout

| Layout | Correct |
|---|---|
| A | 100% (22/22) |
| B | 100% (29/29) |
| C | 100% (23/23) |
| none (no invoice) | 100% (6/6) |

## Extraction

Invoices found for cases that have one: 74; the right document: 100% (74/74).

| Field | Correct |
|---|---|
| vendor_name | 100% (74/74) |
| invoice_number | 100% (74/74) |
| invoice_date | 100% (74/74) |
| total_amount | 100% (74/74) |
| bank_last4 | 100% (74/74) |
| service_category | 100% (74/74) |

## Cost and speed

| Measure | Result |
|---|---|
| Total cost (estimated) | $0.00 |
| Cost per case | $0.0000 |
| Input / output tokens | 0 / 0 |
| Cache read / write tokens | 0 / 0 |
| Seconds per case | 0.00 |
| Tool calls per case | 0.0 |
