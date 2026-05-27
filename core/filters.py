"""
Shared filters and data-quality helpers.

Responsibilities:
1. Reject non-company names (page chrome, CTAs, template text).
2. Sanitize / validate individual data fields (phone, email, address, etc.).
3. Provide a ``sanitize_company_data()`` entry-point that the orchestrator
   calls *before* inserting into the database.
"""

import re
from typing import Optional

# ── Company-name validation ──────────────────────────────────────────────────

# Phrases that are clearly page chrome, not company names
_JUNK_PHRASES = re.compile(
    r"business directory|post buy requirement|list of suppliers|"
    r"showcase your|save time|business listing|add your business|"
    r"advertise here|your company here|free listing|register now|"
    r"sign up|log in|contact us|about us|home|search results|"
    r"no results|page not found|loading\.\.\.",
    re.IGNORECASE,
)

# Must contain at least one actual word character (letter)
_HAS_LETTER = re.compile(r"[a-zA-ZÀ-ÿ؀-ۿ]")


def is_valid_company_name(name: str) -> bool:
    """Return True when *name* looks like a real company name."""
    if not name or not isinstance(name, str):
        return False
    name = name.strip()
    if len(name) < 3 or len(name) > 120:
        return False
    if not _HAS_LETTER.search(name):
        return False
    if _JUNK_PHRASES.search(name):
        return False
    return True


def filter_companies(companies: list[dict], name_key: str = "name") -> list[dict]:
    """Keep only entries whose name passes validation."""
    return [c for c in companies if is_valid_company_name(c.get(name_key, ""))]


# ── Placeholder / junk-value detection ───────────────────────────────────────

# Patterns that indicate a masked or placeholder value
_PLACEHOLDER_RE = re.compile(
    r"^[x\*#\.]{3,}$"           # "xxxxx", "***", "###", "....."
    r"|^[0\-\s]{5,}$"           # "00000", "-----"
    r"|^n/?a$"                  # "n/a", "N/A"
    r"|^none$"                  # "none"
    r"|^null$"                  # "null"
    r"|^not\s*available$"       # "not available"
    r"|^unknown$"               # "unknown"
    r"|^-+$"                    # "---"
    r"|^\?+$",                  # "???"
    re.IGNORECASE,
)


def _is_placeholder(value: str) -> bool:
    """Return True when the string looks like a masked or placeholder value."""
    return bool(_PLACEHOLDER_RE.match(value.strip()))


# ── Phone validation ────────────────────────────────────────────────────────

# A Tunisian (or international) phone should have at least 6 digits
_DIGITS_RE = re.compile(r"\d")
_MIN_PHONE_DIGITS = 6


def sanitize_phone(raw: Optional[str]) -> str:
    """Return a cleaned phone string or empty string if invalid.

    Discards:
    - Placeholder values ('xxxxx', 'n/a', etc.)
    - Values with fewer than 6 digits (too short to be real)
    - Values that are entirely non-numeric junk
    """
    if not raw or not isinstance(raw, str):
        return ""
    raw = raw.strip()
    if not raw:
        return ""
    if _is_placeholder(raw):
        return ""
    # Count actual digits
    digit_count = len(_DIGITS_RE.findall(raw))
    if digit_count < _MIN_PHONE_DIGITS:
        return ""
    return raw


# ── Email validation ────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)


def sanitize_email(raw: Optional[str]) -> str:
    """Return a cleaned email string or empty string if invalid."""
    if not raw or not isinstance(raw, str):
        return ""
    raw = raw.strip().lower()
    if not raw:
        return ""
    if _is_placeholder(raw):
        return ""
    if not _EMAIL_RE.match(raw):
        return ""
    # Reject obviously fake domains
    fake_domains = {"example.com", "test.com", "fake.com", "email.com", "none.com"}
    domain = raw.split("@")[-1]
    if domain in fake_domains:
        return ""
    return raw


# ── Website validation ──────────────────────────────────────────────────────

def sanitize_website(raw: Optional[str]) -> str:
    """Return a cleaned website URL or empty string if invalid."""
    if not raw or not isinstance(raw, str):
        return ""
    raw = raw.strip()
    if not raw:
        return ""
    if _is_placeholder(raw):
        return ""
    # Reject stub URLs
    stubs = {"www.", "http://www.", "https://www.", "http://", "https://"}
    if raw.lower() in stubs:
        return ""
    # Must contain at least one dot (domain separator)
    if "." not in raw:
        return ""
    return raw


# ── Address validation ──────────────────────────────────────────────────────

def sanitize_address(raw: Optional[str]) -> str:
    """Return a cleaned address or empty string if too short / placeholder."""
    if not raw or not isinstance(raw, str):
        return ""
    raw = raw.strip()
    if not raw:
        return ""
    if _is_placeholder(raw):
        return ""
    # An address shorter than 5 chars is unlikely to be useful
    if len(raw) < 5:
        return ""
    return raw


# ── Master sanitiser ────────────────────────────────────────────────────────

def sanitize_company_data(data: dict) -> dict:
    """Sanitize all fields in a company dict before DB insertion.

    Modifies and returns the same dict. Clears any field whose value
    looks like a placeholder or is otherwise invalid.
    """
    # Phone fields
    for key in ("phone",):
        if key in data:
            data[key] = sanitize_phone(data.get(key))

    # Email fields
    for key in ("email",):
        if key in data:
            data[key] = sanitize_email(data.get(key))

    # Website fields
    for key in ("website",):
        if key in data:
            data[key] = sanitize_website(data.get(key))

    # Address fields
    for key in ("address",):
        if key in data:
            data[key] = sanitize_address(data.get(key))

    # Generic string fields: strip and clear if placeholder
    for key in ("sector", "field", "description", "legal_name"):
        val = data.get(key)
        if isinstance(val, str):
            val = val.strip()
            if _is_placeholder(val):
                val = ""
            data[key] = val

    return data
