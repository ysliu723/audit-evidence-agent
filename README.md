# Audit Evidence Agent

An AI agent that vouches flagged journal entries against the evidence behind them: the vendor invoice, the
purchase order, the receiving record, and the contract. Claude reads the PDFs and cites a page and an exact
line for every value; code verifies every citation and runs eight checks; a reviewer signs off.

**Python · Claude API (tool use, strict schemas) · PDF parsing · FastAPI · SQLAlchemy · pytest · Docker**

[![tests](https://github.com/ysliu723/audit-evidence-agent/actions/workflows/tests.yml/badge.svg)](https://github.com/ysliu723/audit-evidence-agent/actions/workflows/tests.yml)

## Why

Vouching means tracing an entry back to its documents: was this invoice for goods that were ordered, at the
ordered price, and actually received? Is the vendor real, and has the invoice been paid before? It is slow,
manual work, and it catches what rules on the ledger cannot. The
[risk platform](https://github.com/ysliu723/ledger-audit-services/tree/main/risk) caught 0% of invoices from a
look-alike vendor, because that fraud looks normal on every number in the ledger. The difference only shows in
the documents.

| Layer | Where | What it handles |
|---|---|---|
| Prevent | [ledger](https://github.com/ysliu723/ledger-audit-services/tree/main/ledger) | What is always wrong: unbalanced, duplicate, or self-approved entries |
| Detect | [risk](https://github.com/ysliu723/ledger-audit-services/tree/main/risk) | What is only sometimes wrong: late-night, round, near-threshold entries |
| **Verify** | **this project** | What only the evidence can tell: a look-alike vendor, a changed bank account, goods never received |

## How it works

```text
flagged entry ──► Claude, with four tools limited to the case's own folder:
                    list_documents · search_documents (matching lines) · read_page · submit_findings
                    at most 8 model calls, a time limit for the run
                    │
                    ▼
       findings: every field with its page and exact line; amounts labeled subtotal / tax / total due
                    │
                    ▼
       citation check, in code: is the line on that page, does it show the value, does its label fit
       the role, is it text addressed to automated reviewers?  ──fails──► sent back (2 tries per field)
                    │
                    ▼
       8 checks in code (Decimal money) ──► SUPPORTED / EXCEPTION / NEEDS_REVIEW
                    │
                    ▼
       memo (template, or a Claude draft that may use only figures from the evidence) ──► reviewer sign-off
```

**Should this be an agent?** Which documents to read and which lines matter depends on the entry and on each
vendor's layout, so the reading is open-ended; an error is recoverable, because code verifies every quote and a
person reviews every memo. Everything that does not need judgment stays in code.

### Design decisions

- **The model reads; code judges.** Claude finds the documents and reports what they say. Comparing
  quantities and prices across the invoice, purchase order, and receiving record, the arithmetic, the dates,
  the vendor master, the approval limits, and the paid-invoice register are deterministic code, so they can be
  tested and cannot be talked out of a result.
- **Every value is cited, and every citation is checked.** A value is used only if its line is on the cited
  page and shows that value. A real line can still back the wrong value: an invoice prints a subtotal, a tax,
  and a total due, and reading the subtotal as the total passes a plain quote check. So amounts carry roles,
  and the cited line's own label must fit the role. A citation that fails goes back to the model with the
  reason, at most twice per field; after that the check that needs it reports UNABLE and a person looks.
- **Absence of evidence is decided by code.** Whether the folder has a receiving record is a fact about the
  folder, not the model's opinion: no receiving record fails; a receiving record the model could not read is
  UNABLE.
- **Documents are data, not instructions.** Tools reach only the case's own files; the backend checks every
  tool name, its arguments, and that the document is in the case's folder, and records every refusal. Text
  addressed to automated reviewers is never accepted as evidence and flags the case for a person.
- **Only text PDFs are read.** A scanned page has no text layer; it is reported as unreadable rather than
  guessed, and the checks that need it go to a person.
- **API usage:** `claude-opus-5-5` with effort set explicitly, strict tool schemas, prompt caching, and
  server-side refusal fallbacks. A refusal, a run that hits a limit, or an unusable answer sends the case to
  NEEDS_REVIEW, never to a pass.
- **Reproducible without a key.** Live runs can be recorded and replayed exactly; the tests drive the agent
  loop with scripted answers, including tool errors, corrections, refusals, and limits.

## The checks

| Check | Fails when |
|---|---|
| VENDOR_IDENTITY | the invoice's vendor is not in the vendor master (look-alike names are called out), or its tax ID or bank account differs from the master |
| DOCUMENT_LINKS | the invoice does not cite the purchase order in the folder, the receiving record is for another order, or a document is missing |
| QUANTITY | more is billed than was ordered or received |
| UNIT_PRICE | a unit price is not the purchase order's price |
| ARITHMETIC | quantity × price, the lines, the subtotal, the tax, and the total do not add up, or the total due is not the entry amount |
| DATES | the goods were invoiced before they were ordered, received after the year end of an entry posted in that year, or invoiced outside the contract term |
| APPROVAL | the purchase order's approver is not authorized for its amount, or also prepared the entry |
| DUPLICATES | the invoice was already paid by another entry |

## Evaluation

80 synthetic cases, each a flagged entry with its own folder of PDFs (298 in all), across 19 scenarios:
supported, look-alike vendor, changed bank account, missing receiving record, wrong order referenced, quantity
above what was received, price above the order, arithmetic error, amount mismatch, cut-off, order dated after
the invoice, expired contract, approval over the limit, self-approval, duplicate invoice, prompt injection, a
subtotal on page 1 with the total on page 2, line items split across pages, and scanned invoices. Every company,
person, and figure is fictional.

- **20 dev cases** (invoice layouts A and B) were used while writing the prompt and the template baseline.
  **60 held-out cases** are scored once; 10 of them use layouts C, D, and E, which appear in no dev case.
- **Each case has eight checks, so the 60 held-out cases give 480 decisions.** A decision is right only if
  the check's result equals the label (PASS, FAIL, or UNABLE). Abstaining on a clear answer counts as wrong;
  abstaining is right only where the evidence cannot be read (a scanned invoice).
- The labels come from the scenario each case was generated for (`scripts/generate_cases.py`).

| Extractor | Held-out accuracy | Familiar layouts | Unseen layouts | Notes |
|---|---|---|---|---|
| Oracle (perfect reading) | **100%** (480/480) | 100% | 100% | The checks themselves make no mistakes on any of the 640 decisions: [docs/evaluation-oracle.md](docs/evaluation-oracle.md) |
| Template baseline, no AI | **88.5%** (425/480) | 100% (400/400) | **31.2%** (25/80) | Reads the layouts it was written for perfectly and breaks on new ones: [docs/evaluation-rules.md](docs/evaluation-rules.md) |
| Claude | *not run yet* | | | Needs an API key; see below |

The template baseline shows the problem a model solves here: fixed labels work on the layouts someone wrote
them for, and every one of its 55 misses on new layouts is an abstention (it never guesses, so the cases go to
a person). On familiar layouts it is perfect, so it is not a strawman.

### Cost and latency

The agent can retrieve in two ways, so their cost can be measured on the same cases with the same model:
`baseline` (search says only which pages match; a page read twice is sent twice) and `optimized` (search
returns the matching lines, so the model often needs fewer pages, and a page is never sent twice). Every run
records tokens, estimated cost, model calls, corrections, refused tool calls, and latency per case;
`evaluation/compare.py` compares two runs. *Not run yet.*

## Quick start

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

pytest                                         # 81 tests, no API key needed
python -m app.cli vouch CASE-021               # vouch one case with the template baseline; prints the memo
python -m evaluation.evaluate --extractor rules
python -m scripts.generate_cases               # rebuild the cases and PDFs (deterministic; CI checks they match)
uvicorn app.main:app --port 8002               # API, docs at http://localhost:8002/docs
docker compose up --build                      # the same API in Docker
```

### Running Claude

Live runs call the Claude API and cost money. Set `ANTHROPIC_API_KEY` in your shell (never in a file), then
start small. Without `--yes` the command prints an estimate and stops.

```bash
python -m evaluation.evaluate --extractor claude --split dev --cases 5 --record --yes      # a first look
python -m evaluation.evaluate --extractor claude --record --yes                             # 60 held-out cases
python -m evaluation.evaluate --extractor claude --profile baseline --record --yes          # the other retrieval
python -m evaluation.compare docs/results/claude-baseline.json docs/results/claude-optimized.json
python -m evaluation.evaluate --extractor claude --replay                                   # again, free
```

`EVIDENCE_AGENT_MODEL`, `EVIDENCE_AGENT_EFFORT`, and `EVIDENCE_AGENT_TIME_LIMIT` change the model, the
effort, and the time limit per case.

## API

| Method | Path | |
|---|---|---|
| GET | `/cases` | The cases waiting to be vouched |
| POST | `/cases/{case_id}/vouch?extractor=rules\|claude\|replay` | Vouch one; returns the checks with sources and the memo |
| GET | `/results`, `/results/{id}` | Saved results (`?status=EXCEPTION`), with their reviews |
| POST | `/results/{id}/reviews` | Approve, edit (with a new summary), or reject (with notes) |

Reviews are never overwritten; the latest one is the current decision.

## Limitations

- **The Claude results are not measured yet**, so this README makes no claim about them.
- **Synthetic, text-layer PDFs.** Scanned pages are reported as unreadable; OCR is not covered.
- **Keyword search over one case's folder.** Enough for a folder of a few documents; a large document set
  would need better retrieval.
- **Cost figures are estimates** from token counts and list prices.
- **No authentication**, and results are kept in SQLite.
