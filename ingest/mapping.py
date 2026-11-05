"""Header mapping (spec section 5): dictionary, simulated agent proposals and analyst approvals."""
import json
from pathlib import Path
from typing import Callable

from ingest.errors import RunError
from ingest.models import ColumnMap, Warning
from ingest.text import match_key

STAGE = "map"
FIELDS = ["card_number", "first_name", "last_name", "email", "phone", "app_installed", "consent",
          "subscription", "last_interaction_at", "last_purchase_at", "last_purchase_amount"]

# A proposer returns (field or None, score 0-100, reason) for one column, never a field already taken.
Proposer = Callable[[str, set[str]], tuple[str | None, int, str]]


def load_dictionary(path: Path) -> dict[str, list[str]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def band(score: int) -> str:
    return "safe" if score > 90 else "caution" if score >= 60 else "none"


def map_header(header: list[str], dictionary: dict[str, list[str]], proposer: Proposer | None = None,
               approved: dict[str, ColumnMap] | None = None) -> tuple[list[ColumnMap], list[dict]]:
    """Map every header cell; returns the maps and the proposals for columns the dictionary does not know."""
    lookup = {match_key(name): f for f, names in dictionary.items() for name in names}
    approved = approved or {}
    maps: list[ColumnMap] = []
    unresolved: list[int] = []
    for column in header:
        if column in approved:
            maps.append(approved[column])
        elif match_key(column) in lookup:
            maps.append(ColumnMap(column, lookup[match_key(column)], "dictionary"))
        else:
            maps.append(ColumnMap(column, None, "passed_through"))
            unresolved.append(len(maps) - 1)
    _check_twice(maps)
    proposals = []
    if proposer is not None:
        taken = {m.field for m in maps if m.field}
        for index in unresolved:
            field, score, reason = proposer(maps[index].column, taken)
            if field in taken:
                field, score, reason = None, 0, "field already mapped by another column"
            proposals.append({"column": maps[index].column, "field": field if score >= 60 else None,
                              "score": score, "band": band(score), "reason": reason,
                              "decision": "", "use_field": ""})
            if score >= 60 and field:
                taken.add(field)
    if not any(p["score"] >= 60 for p in proposals) and not any(m.field == "card_number" for m in maps):
        raise RunError("CARD_COLUMN_MISSING", "No column was recognized as the loyalty card number", STAGE)
    return _suffix_unknown(maps), proposals


def _check_twice(maps: list[ColumnMap]) -> None:
    seen: dict[str, str] = {}
    for m in maps:
        if m.field and m.field in seen:
            raise RunError("FIELD_MAPPED_TWICE",
                           f"Columns {seen[m.field]} and {m.column} both map to {m.field}; choose one", STAGE)
        if m.field:
            seen[m.field] = m.column


def _suffix_unknown(maps: list[ColumnMap]) -> list[ColumnMap]:
    counts: dict[str, int] = {}
    for m in maps:
        if m.field is None:
            counts[m.column] = counts.get(m.column, 0) + 1
            if counts[m.column] > 1:
                m.column = f"{m.column}_{counts[m.column]}"
    return maps


def mapping_warnings(maps: list[ColumnMap]) -> list[Warning]:
    return [Warning(None, m.column, "UNKNOWN_COLUMN") for m in maps if m.field is None]
