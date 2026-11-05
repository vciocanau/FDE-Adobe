"""Text helpers: control-character removal (spec 6.1) and name matching keys (spec 5)."""
import re
import unicodedata

# Unicode category Cc is exactly U+0000-U+001F and U+007F-U+009F; TAB, LF and CR are kept.
_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def remove_control(value: str) -> tuple[str, bool]:
    """Remove Unicode Cc characters except TAB, LF and CR; report whether any was removed."""
    cleaned = _CONTROL.sub("", value)
    return cleaned, len(cleaned) != len(value)


def match_key(name: str) -> str:
    """Normalize a column name for whole-name comparison."""
    decomposed = unicodedata.normalize("NFKD", name.strip().lower())
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return "".join(ch for ch in without_marks if ch not in " -._\t")
