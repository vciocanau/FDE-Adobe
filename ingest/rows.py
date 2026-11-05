"""Stage 2, clean: field rules, rejection, duplicates and eligibility (spec sections 6 and 7)."""
from datetime import datetime

from ingest import fields
from ingest.models import ColumnMap, Duplicate, Outcome, ReadResult, Rejected, Warning
from ingest.text import remove_control

CANONICAL = ["card_number", "first_name", "last_name", "email", "phone", "app_installed", "consent",
             "subscription", "last_interaction_at", "last_purchase_at", "last_purchase_amount"]
OUTPUT_COLUMNS = CANONICAL + ["eligible_for_campaign", "ineligibility_reasons", "source_record_number"]

_CLEANERS = {
    "first_name": fields.clean_name, "last_name": fields.clean_name, "email": fields.clean_email,
    "phone": fields.clean_phone, "app_installed": fields.clean_app, "consent": fields.clean_consent,
    "subscription": fields.clean_subscription, "last_purchase_amount": fields.clean_amount,
}
_MISSING_DEFAULT = {"consent": "unknown", "subscription": "unknown", "app_installed": "unknown"}


def process(read: ReadResult, maps: list[ColumnMap], run_time: datetime, check=None) -> Outcome:
    """Clean every record; `check` is called every 10,000 records (memory guard, spec 10.3)."""
    mapped = {m.field for m in maps if m.field}
    warnings = list(read.warnings)
    rejected = list(read.rejected)
    for field in ("consent", "subscription"):
        if field not in mapped:
            warnings.append(Warning(None, None, f"{field.upper()}_COLUMN_MISSING"))

    rows: list[dict] = []
    for index, record in enumerate(read.records, start=1):
        if check and index % 10_000 == 0:
            check()
        row, row_warnings, card_codes = _clean_record(record.cells, maps, run_time, record.number)
        if card_codes:
            rejected.append(Rejected(record.number, card_codes, record.original))
            continue
        warnings.extend(row_warnings)
        row["_number"] = record.number
        rows.append(row)

    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["card_number"], []).append(row)

    canonical, duplicates = [], []
    for card, group in groups.items():
        winner, losers, conflict = _resolve(group)
        for loser, reason in losers:
            duplicates.append(Duplicate(card, loser["_number"], loser["last_interaction_at"], winner["_number"], reason))
            if reason == "LOST_TIE_LATER_ROW_WINS":
                warnings.append(Warning(winner["_number"], "last_interaction_at", "DUPLICATE_TIE"))
        if conflict:
            warnings.append(Warning(winner["_number"], None, "DUPLICATE_CONFLICT"))
        reasons = _ineligibility(winner, mapped, conflict)
        if "NO_CONTACT_CHANNEL" in reasons:
            warnings.append(Warning(winner["_number"], None, "NO_CONTACT_CHANNEL"))
        out = {column: winner.get(column, "") for column in CANONICAL}
        out["eligible_for_campaign"] = "no" if reasons else "yes"
        out["ineligibility_reasons"] = ";".join(reasons)
        out["source_record_number"] = str(winner["_number"])
        out.update(winner["_pass"])
        canonical.append((winner["_number"], out))

    canonical.sort(key=lambda item: item[0])
    rejected.sort(key=lambda r: r.record)
    duplicates.sort(key=lambda d: d.record)
    return Outcome([row for _, row in canonical], rejected, duplicates, warnings)


def _clean_record(cells, maps, run_time, number):
    row = dict(_MISSING_DEFAULT)
    row["_pass"] = {}
    warnings: list[Warning] = []
    card_codes: list[str] = []
    for cell, m in zip(cells, maps):
        if m.field is None:
            value, removed = remove_control(cell)
            row["_pass"][m.column] = value
            if removed:
                warnings.append(Warning(number, m.column, "CONTROL_CHARACTER_REMOVED"))
            continue
        if m.field == "card_number":
            result = fields.clean_card(cell)
            card_codes = [c for c in result.codes if c in ("CARD_EMPTY", "CARD_INVALID")]
        elif m.field in ("last_interaction_at", "last_purchase_at"):
            result = fields.parse_timestamp(cell, run_time)
        else:
            result = _CLEANERS[m.field](cell)
        row[m.field] = result.value
        warnings.extend(Warning(number, m.field, code) for code in result.codes
                        if code not in ("CARD_EMPTY", "CARD_INVALID"))
    return row, warnings, card_codes


def _resolve(group: list[dict]):
    """Spec 7.2: the most recent valid timestamp wins; ties and unusable timestamps go to the later record."""
    if len(group) == 1:
        return group[0], [], False
    def key(row):
        ts = row["last_interaction_at"]
        return (1, fields.timestamp_sort_key(ts), row["_number"]) if ts else (0, None, row["_number"])

    def sort_key(row):
        has, moment, number = key(row)
        return (has, moment.timestamp() if moment else 0, number)

    ordered = sorted(group, key=sort_key)
    winner = ordered[-1]
    losers, conflict = [], False
    for row in ordered[:-1]:
        if not row["last_interaction_at"] and winner["last_interaction_at"]:
            reason = "LOST_INVALID_TIMESTAMP"
        elif row["last_interaction_at"] and sort_key(row)[1] < sort_key(winner)[1]:
            reason = "LOST_OLDER_TIMESTAMP"
        else:
            reason = "LOST_TIE_LATER_ROW_WINS"
        undecided = reason != "LOST_OLDER_TIMESTAMP"
        if undecided and (row["consent"], row["subscription"]) != (winner["consent"], winner["subscription"]):
            conflict = True
        losers.append((row, reason))
    return winner, losers, conflict


def _ineligibility(row: dict, mapped: set[str], conflict: bool) -> list[str]:
    reasons = []
    if "consent" not in mapped:
        reasons.append("CONSENT_COLUMN_MISSING")
    elif row["consent"] != "yes":
        reasons.append("CONSENT_NOT_YES")
    if "subscription" not in mapped:
        reasons.append("SUBSCRIPTION_COLUMN_MISSING")
    elif row["subscription"] != "active":
        reasons.append("SUBSCRIPTION_NOT_ACTIVE")
    if not (row.get("email") or row.get("phone") or row.get("app_installed") == "yes"):
        reasons.append("NO_CONTACT_CHANNEL")
    if conflict:
        reasons.append("CONFLICTING_DUPLICATES")
    return reasons


def run_flags(outcome: Outcome, rows_received: int, thresholds: dict) -> list[Warning]:
    """Spec 7.4: run warnings for the missing-contact and rejection thresholds."""
    warnings = []
    canonical = len(outcome.canonical)
    no_contact = sum("NO_CONTACT_CHANNEL" in r["ineligibility_reasons"] for r in outcome.canonical)
    if canonical and no_contact * 100 > thresholds["missing_contact_pct"] * canonical:
        warnings.append(Warning(None, None, "MISSING_CONTACT_THRESHOLD"))
    if rows_received and len(outcome.rejected) * 100 > thresholds["rejection_pct"] * rows_received:
        warnings.append(Warning(None, None, "REJECTION_RATE_HIGH"))
    return warnings
