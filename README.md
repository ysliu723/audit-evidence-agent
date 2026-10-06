# Audit Evidence Agent

An AI assistant that vouches flagged journal entries against invoices, contracts,
and the vendor master. Claude finds and reads the evidence; code verifies every
quote and makes every decision; a reviewer signs off.

**Python · Claude API (tool use, structured outputs) · FastAPI · SQLAlchemy · pytest · Docker**

[![tests](https://github.com/ysliu723/audit-evidence-agent/actions/workflows/tests.yml/badge.svg)](https://github.com/ysliu723/audit-evidence-agent/actions/workflows/tests.yml)

## Why

Vouching means tracing an entry back to its evidence: is there an invoice, does
it match, is the vendor real, was it already paid? It is slow, manual work, and
it catches what rules on the ledger cannot. The sister project, the
[Journal Entry Risk Platform](https://github.com/ysliu723/journal-entry-risk-platform),
caught 0% of invoices from a look-alike vendor, because that fraud looks normal
on every number in the ledger. The difference only shows in the documents.

Three layers of defense across the projects:

| Layer | Project | What it handles |
|---|---|---|
| Prevent | [Payments Ledger Service](https://github.com/ysliu723/payments-ledger-service) | What is always wrong: unbalanced, duplicate, or self-approved entries |
| Detect | Journal Entry Risk Platform | What is only sometimes wrong: late-night, round, near-threshold entries |
| **Verify** | **this project** | What only the evidence can tell: a look-alike vendor, a changed bank account |

## How it works

```text
flagged entry ──► Claude ──search_documents / read_document──► evidence store (241 documents)
                    │   (up to 8 turns)
                    ▼
       extraction as JSON (structured output): every field with its page and exact quote
                    │
                    ▼
       citation check: is the quote on that page, does it show the value,
                       is it text addressed to automated reviewers?
                    │
                    ▼
       8 checks in code ──► SUPPORTED / EXCEPTION / NEEDS_REVIEW / MISSING_EVIDENCE
                    │
                    ▼
       memo (Claude drafts; any figure not in the evidence → standard wording) ──► reviewer sign-off
```

**Should this be an agent?** Finding one invoice among a client's documents is
open-ended (the right search depends on what the entry says), worth doing, and
something Claude reads well; and an error is recoverable, because code verifies
every quote and a person reviews every memo. Everything that does *not* need
judgment stays in code.

### Design decisions

- **The model reads; code judges.** Claude finds the documents and reports what
  they say. Comparing amounts and dates, matching the vendor master, and checking
  the paid-invoice register are deterministic code, so they can be tested and
  cannot be talked out of a result.
- **Every value must be cited, and every citation is checked.** A value is used
  only if its quote is on the cited page and shows that value. Otherwise the check
  that needs it reports UNABLE and a person looks.
- **Documents are evidence, not instructions.** An invoice that tells "automated
  reviewers" what to report fails DOCUMENT_INTEGRITY by itself (to an auditor that
  is a red flag), and any value quoted from such text is refused.
- **When in doubt, a person decides.** A refusal, a run that hits its turn limit,
  or an unreadable answer sends the case to NEEDS_REVIEW, never to "no evidence".
- **API usage:** `claude-opus-5-5` with effort set explicitly (`medium` to
  extract, `low` to draft memos), strict tools, `output_config` JSON schemas,
  automatic prompt caching, and server-side refusal fallbacks.
- **Reproducible without a key.** Live runs can be recorded and replayed exactly;
  tests drive the agent loop with a scripted API.

## The checks

| Check | Fails when |
|---|---|
| SUPPORTING_DOCUMENT | no invoice supporting the entry is found |
| DOCUMENT_INTEGRITY | the invoice contains instructions to its reviewer |
| AMOUNT_MATCH | the invoice total differs from the entry amount |
| CUTOFF | an entry in this fiscal year is supported by an invoice dated after year end |
| VENDOR_APPROVED | the vendor is not in the vendor master (look-alike names are called out) |
| BANK_ACCOUNT | the remit-to account differs from the one on file |
| DUPLICATE_INVOICE | the invoice was already paid by another entry |
| CONTRACT_SCOPE | the services are outside the contract, or exceed its limit |

## Evaluation

80 synthetic cases across nine scenarios (supported, amount mismatch, cut-off,
look-alike vendor, changed bank account, missing document, duplicate invoice,
out of scope, prompt injection), with invoices in three layouts and several date
and amount formats, plus other invoices from the same vendors to choose between.
A case counts as correct only if the overall status and the exact set of failed
checks both match.

| Extractor | Cases correct | Notes |
|---|---|---|
| Oracle (perfect extraction) | **100%** (80/80) | The checks themselves make no mistakes: [docs/evaluation-oracle.md](docs/evaluation-oracle.md) |
| Rules, no AI | **71%** (57/80) | 100% on the two layouts the rules were written for, **0% on the unseen third**: [docs/evaluation-rules.md](docs/evaluation-rules.md) |
| Claude | *not run yet* | Needs an API key; see below |
| Claude deciding the checks itself | *not run yet* | The comparison experiment |

The rule-based baseline shows the problem an LLM solves here: rules work on the
layouts someone wrote them for and break on the next one. The Claude rows will
be filled in from a recorded run, with its measured cost.

## Quick start

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

pytest                                         # 71 tests, no API key needed
python -m app.cli vouch CASE-010               # vouch one case with the rules; prints the memo
python -m evaluation.evaluate --extractor rules
uvicorn app.main:app --port 8002               # API, docs at http://localhost:8002/docs
docker compose up --build                      # the same API in Docker
```

### Running Claude

Live runs call the Claude API and cost money. Set `ANTHROPIC_API_KEY` in your
shell (never in a file), then start small:

```bash
python -m evaluation.evaluate --extractor claude --cases 10 --record --yes
python -m evaluation.evaluate --extractor claude --record --yes        # all 80 cases
python -m evaluation.evaluate --extractor claude --replay              # rerun from recordings, free
```

Without `--yes` it prints an estimate and stops. `EVIDENCE_AGENT_MODEL` and
`EVIDENCE_AGENT_EFFORT` change the model and effort.

## API

| Method | Path | |
|---|---|---|
| GET | `/cases` | The cases waiting to be vouched |
| POST | `/cases/{case_id}/vouch?extractor=rules\|claude\|replay` | Vouch one; returns findings with sources and the memo |
| GET | `/results`, `/results/{id}` | Saved results (`?status=EXCEPTION`), with their reviews |
| POST | `/results/{id}/reviews` | Approve, edit (with a new summary), or reject (with notes) |

Reviews are never overwritten; the latest one is the current decision.

## Limitations

- **The Claude results are not measured yet**, so this README makes no claim about them.
- **Synthetic, text-only documents.** Real evidence comes as scanned PDFs; OCR is not covered.
- **Keyword search.** Fine for invoice numbers and vendor names; a large store would need better retrieval.
- **Cost figures are estimates** from token counts and list prices.
- **No authentication**, and results are kept in SQLite.
