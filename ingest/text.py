"""Text helpers: control-character removal (spec 6.1) and name matching keys (spec 5)."""
import unicodedata

_KEEP = {"\t", "\n", "\r"}


def remove_control(value: str) -> tuple[str, bool]:
    """Remove Unicode Cc characters except TAB, LF and CR; report whether any was removed."""
    cleaned = "".join(ch for ch in value if ch in _KEEP or unicodedata.category(ch) != "Cc")
    return cleaned, cleaned != value


def match_key(name: str) -> str:
    """Normalize a column name for whole-name comparison."""
    decomposed = unicodedata.normalize("NFKD", name.strip().lower())
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return "".join(ch for ch in without_marks if ch not in " -._\t")
