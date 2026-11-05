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
