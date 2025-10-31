"""
utils.py
Shared helpers: email validation, Drive link parsing, PDF text extraction, etc.
"""

import re
import io
from pypdf import PdfReader
from urllib.parse import urlparse, parse_qs

EMAIL_RE_STRICT = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.I)
EMAIL_RE_LOOSE  = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)


def valid_email(addr: str | None) -> str:
    """Return a clean email if syntactically valid, else ''."""
    if addr and EMAIL_RE_STRICT.match(addr.strip()):
        return addr.strip()
    return ""


def extract_any_email_from_text(blob: str) -> str:
    """Fallback: pull first thing that 'looks like' an email from raw resume text."""
    if not blob:
        return ""
    m = EMAIL_RE_LOOSE.search(blob)
    return m.group(0).strip() if m else ""


def extract_drive_file_id(url: str | None) -> str | None:
    """Try multiple URL patterns to get a Google Drive file ID."""
    if not url:
        return None

    # pattern like /file/d/<FILEID>/view
    m = re.search(r"/file/d/([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)

    # pattern like ?id=<FILEID>
    qs = parse_qs(urlparse(url).query)
    if "id" in qs and qs["id"]:
        return qs["id"][0]

    # fallback: guess long token-looking chunk
    parts = urlparse(url).path.strip("/").split("/")
    for token in parts:
        if re.match(r"^[a-zA-Z0-9_-]{20,}$", token):
            return token

    return None


def pdf_to_text(path: str, max_pages: int = 15) -> str:
    """Extract text from first N pages of a PDF résumé."""
    try:
        reader = PdfReader(path)
        pages = reader.pages[:max_pages]
        return "\n".join((p.extract_text() or "") for p in pages)
    except Exception:
        return ""
