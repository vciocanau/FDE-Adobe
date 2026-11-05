"""Field rules (spec section 6). Every function takes the raw cell and returns a FieldResult."""
import re
import unicodedata

from ingest.models import FieldResult
from ingest.text import remove_control

CONTROL = "CONTROL_CHARACTER_REMOVED"
_CEDILLA = str.maketrans({"ş": "ș", "ţ": "ț", "Ş": "Ș", "Ţ": "Ț"})


def _strip_control(raw: str) -> tuple[str, list[str]]:
    value, removed = remove_control(raw)
    return value, [CONTROL] if removed else []


def clean_card(raw: str) -> FieldResult:
    """Spec 6.2: exactly 16 ASCII digits after removing whitespace and dashes."""
    value, codes = _strip_control(raw)
    value = "".join(ch for ch in value if not ch.isspace() and ch != "-")
    if not value:
        return FieldResult("", codes + ["CARD_EMPTY"])
    if not re.fullmatch(r"[0-9]{16}", value, re.ASCII):
        return FieldResult("", codes + ["CARD_INVALID"])
    return FieldResult(value, codes)


def clean_name(raw: str) -> FieldResult:
    """Spec 6.3: trimmed, inner whitespace collapsed, NFC, cedilla to comma-below."""
    value, codes = _strip_control(raw)
    value = unicodedata.normalize("NFC", " ".join(value.split())).translate(_CEDILLA)
    return FieldResult(value, codes)


def clean_phone(raw: str) -> FieldResult:
    """Spec 6.4: digits and a leading plus; Romanian forms become +40; 8 to 15 digits."""
    value, codes = _strip_control(raw)
    value = value.strip()
    if not value:
        return FieldResult("", codes)
    plus = value.startswith("+")
    digits = "".join(ch for ch in value if ch in "0123456789")
    if plus:
        number = "+" + digits
    elif digits.startswith("0040"):
        number = "+40" + digits[4:]
    elif digits.startswith("0") and not digits.startswith("00"):
        number = "+40" + digits[1:]
    elif len(digits) == 9 and digits.startswith("7"):
        number = "+40" + digits
        codes = codes + ["PHONE_LEADING_ZERO"]
    else:
        number = digits
    count = sum(ch.isdigit() for ch in number)
    if count < 8 or count > 15:
        return FieldResult("", [c for c in codes if c != "PHONE_LEADING_ZERO"] + ["PHONE_INVALID"])
    return FieldResult(number, codes)


def clean_email(raw: str) -> FieldResult:
    """Spec 6.5: trimmed and lowercased; no spaces, exactly one @, a dot after the @."""
    value, codes = _strip_control(raw)
    value = value.strip().lower()
    if not value:
        return FieldResult("", codes)
    local, _, domain = value.partition("@")
    if any(ch.isspace() for ch in value) or value.count("@") != 1 or not local or "." not in domain:
        return FieldResult("", codes + ["EMAIL_INVALID"])
    return FieldResult(value, codes)
