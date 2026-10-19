"""Reading a PDF's text layer, page by page.

Only text PDFs are read. A page with no text layer (a scan, a photo) comes back empty and is reported as a
parse failure, so a person reads it: nothing on such a page is ever guessed.
"""

from functools import lru_cache
from pathlib import Path

from pypdf import PdfReader


@lru_cache(maxsize=512)
def read_pages(path: Path) -> tuple[str, ...]:
    """Each page's text, lines kept in order. Cached: a document is parsed once however often it is read."""
    reader = PdfReader(str(path))
    return tuple((page.extract_text() or "").strip() for page in reader.pages)
