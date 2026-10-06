"""Spotting documents that try to instruct whoever reviews them.

A genuine invoice never tells "automated review systems" what to report.
Text like that is a prompt-injection attempt aimed at AI tools, and to an
auditor it is also a red flag about the document itself. This check is
plain pattern matching on the document, so it works whether or not the
model was fooled.
"""

import re

from app.domain import Document

INSTRUCTION_PATTERNS = [
    re.compile(r"\b(automated|ai)\s+(review|reviewer|reviewers|system|systems|assistant)s?\b", re.IGNORECASE),
    re.compile(r"\bignore\s+(all\s+|any\s+)?(previous|prior|above)\s+instructions\b", re.IGNORECASE),
    re.compile(r"\bmark\s+(every|all|each)\s+checks?\s+as\s+(passed|approved|verified)\b", re.IGNORECASE),
    re.compile(r"\breport\s+the\s+(total|amount)\s+as\b", re.IGNORECASE),
]


def suspicious_lines(document: Document) -> list[str]:
    lines = [line for page in document.pages for line in page.splitlines()]
    return [line for line in lines if any(pattern.search(line) for pattern in INSTRUCTION_PATTERNS)]
