"""Reading amounts and dates the way vendors write them.

    $57,503.29   USD 57,503.29   57,503.29 USD
    2026-11-14   November 14, 2026   14 Nov 2026   11/14/2026
"""

import re
from datetime import date, datetime
from decimal import Decimal

AMOUNT = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})*|\d+)\.(\d{2})(?![\d])")
DATE_PATTERNS = [
    (re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"), "%Y-%m-%d"),
    (re.compile(r"\b([A-Z][a-z]+ \d{1,2}, \d{4})\b"), "%B %d, %Y"),
    (re.compile(r"\b(\d{1,2} [A-Z][a-z]{2} \d{4})\b"), "%d %b %Y"),
    (re.compile(r"\b(\d{2}/\d{2}/\d{4})\b"), "%m/%d/%Y"),  # US style: month first
]


def all_amounts(text: str) -> list[Decimal]:
    return [Decimal(f"{whole.replace(',', '')}.{cents}") for whole, cents in AMOUNT.findall(text)]


def all_dates(text: str) -> list[date]:
    found = []
    for pattern, layout in DATE_PATTERNS:
        for match in pattern.findall(text):
            try:
                found.append(datetime.strptime(match, layout).date())
            except ValueError:
                pass  # looked like a date but is not one, e.g. "February 30, 2026"
    return found


def normalize(text: str) -> str:
    """Lower case, one space between words: for comparing quotes and names."""
    return " ".join(text.lower().split())


def normalize_name(name: str) -> str:
    """For vendor names: "Fabrikam, Inc." and "fabrikam inc" are the same company."""
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", name.lower()).split())
