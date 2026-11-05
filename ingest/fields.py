"""Field rules (spec section 6). Every function takes the raw cell and returns a FieldResult."""
import re
import unicodedata
from functools import lru_cache
from datetime import datetime, timedelta, timezone, tzinfo

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


_DATE_TIME = re.compile(
    r"(?:(?P<iy>\d{4})-(?P<im>\d{2})-(?P<id>\d{2})"
    r"|(?P<dd>\d{2})\.(?P<dm>\d{2})\.(?P<dy>\d{4})"
    r"|(?P<sd>\d{2})/(?P<sm>\d{2})/(?P<sy>\d{4}))"
    r"(?:[ T](?P<h>\d{2}):(?P<mi>\d{2})(?::(?P<s>\d{2}))?(?P<z>Z|[+-]\d{2}:\d{2})?)?",
    re.ASCII,
)


@lru_cache(maxsize=1)
def local_zone() -> tzinfo:
    """The local time zone of the machine, as a fixed offset."""
    return datetime.now().astimezone().tzinfo


def parse_timestamp(raw: str, run_time: datetime, tz: tzinfo | None = None) -> FieldResult:
    """Spec 6.6: day-first dates with an optional time; stored in ISO 8601."""
    value, codes = _strip_control(raw)
    value = value.strip()
    if not value:
        return FieldResult("", codes)
    m = _DATE_TIME.fullmatch(value)
    if not m or (m["z"] and not m["iy"]):
        return FieldResult("", codes + ["TIMESTAMP_UNREADABLE"])
    year, month, day = next((m[a], m[b], m[c]) for a, b, c in
                            (("iy", "im", "id"), ("dy", "dm", "dd"), ("sy", "sm", "sd")) if m[a])
    try:
        if m["h"] is None:
            moment = datetime(int(year), int(month), int(day))
        else:
            moment = datetime(int(year), int(month), int(day), int(m["h"]), int(m["mi"]), int(m["s"] or 0))
    except ValueError:
        return FieldResult("", codes + ["TIMESTAMP_UNREADABLE"])
    if m["z"]:
        offset = timezone.utc if m["z"] == "Z" else timezone(
            (1 if m["z"][0] == "+" else -1) * timedelta(hours=int(m["z"][1:3]), minutes=int(m["z"][4:6])))
        moment = moment.replace(tzinfo=offset)
    stored = moment.date().isoformat() if m["h"] is None else moment.isoformat()
    try:
        compared = _aware(moment, tz).astimezone(timezone.utc)
    except (OverflowError, ValueError):
        return FieldResult("", codes + ["TIMESTAMP_OUT_OF_RANGE"])
    if compared > run_time:
        return FieldResult("", codes + ["TIMESTAMP_IN_FUTURE"])
    return FieldResult(stored, codes)


def _aware(moment: datetime, tz: tzinfo | None) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=tz or local_zone())


def timestamp_sort_key(value: str, tz: tzinfo | None = None) -> datetime:
    """Aware datetime for comparing stored values; a date alone is 00:00:00 local time."""
    return _aware(datetime.fromisoformat(value), tz).astimezone(timezone.utc)


CONSENT_YES = ["da", "yes", "y", "true", "1", "accept", "acept", "accepted", "opt-in", "optin", "ok"]
CONSENT_NO = ["nu", "no", "n", "false", "0", "refuz", "refuzat", "refused", "opt-out", "optout",
              "retras", "withdrawn", "revoked", "nu doresc"]
SUBSCRIPTION_ACTIVE = ["active", "activ", "subscribed", "yes", "da", "y", "true", "1"]
SUBSCRIPTION_INACTIVE = ["inactive", "inactiv", "unsubscribed", "no", "nu", "n", "false", "0"]
APP_YES = ["yes", "da", "y", "true", "1", "installed"]
APP_NO = ["no", "nu", "n", "false", "0"]
STATUS_VALUES = frozenset(CONSENT_YES + CONSENT_NO + SUBSCRIPTION_ACTIVE + SUBSCRIPTION_INACTIVE + APP_YES + APP_NO)


def _consent_key(value: str) -> str:
    return "".join(ch for ch in value.strip().lower() if ch not in " -.")


_CONSENT = {**{_consent_key(v): "yes" for v in CONSENT_YES}, **{_consent_key(v): "no" for v in CONSENT_NO}}
_SUBSCRIPTION = {**{v: "active" for v in SUBSCRIPTION_ACTIVE}, **{v: "inactive" for v in SUBSCRIPTION_INACTIVE}}
_APP = {**{v: "yes" for v in APP_YES}, **{v: "no" for v in APP_NO}}


def _lookup(raw: str, table: dict[str, str], key, unknown_code: str) -> FieldResult:
    value, codes = _strip_control(raw)
    result = table.get(key(value))
    if result is None:
        return FieldResult("unknown", codes + [unknown_code])
    return FieldResult(result, codes)


def clean_consent(raw: str) -> FieldResult:
    """Spec 6.7: yes, no or unknown; spaces, hyphens and dots are ignored; whole value compared."""
    return _lookup(raw, _CONSENT, _consent_key, "CONSENT_UNKNOWN")


def clean_subscription(raw: str) -> FieldResult:
    """Spec 6.8: active, inactive or unknown; trimmed and lowercased; whole value compared."""
    return _lookup(raw, _SUBSCRIPTION, lambda v: v.strip().lower(), "SUBSCRIPTION_UNKNOWN")


def clean_app(raw: str) -> FieldResult:
    """Spec 6.9: yes, no or unknown; only yes is a contact channel."""
    return _lookup(raw, _APP, lambda v: v.strip().lower(), "APP_INSTALLED_UNKNOWN")


def clean_amount(raw: str) -> FieldResult:
    """Spec 6.10: a positive number with an optional decimal part of 1 or 2 digits."""
    value, codes = _strip_control(raw)
    value = value.strip()
    if not value:
        return FieldResult("", codes)
    if not re.fullmatch(r"[0-9]+(?:[.,][0-9]{1,2})?", value, re.ASCII):
        return FieldResult("", codes + ["PURCHASE_AMOUNT_INVALID"])
    value = value.replace(",", ".")
    if float(value) == 0:
        return FieldResult("", codes + ["PURCHASE_AMOUNT_INVALID"])
    return FieldResult(value, codes)
