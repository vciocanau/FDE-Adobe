"""Header mapping (spec section 5): dictionary, simulated agent proposals and analyst approvals."""
import json
from datetime import datetime
from pathlib import Path
from typing import Callable

from ingest.errors import RunError
from ingest.models import ColumnMap, Warning
from ingest.agent import mask
from ingest.text import match_key, remove_control

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
    lookup = {match_key(name): f for f, names in dictionary.items() for name in [f, *names]}
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


def map_header_with_samples(header: list[str], rows: list[list[str]], dictionary: dict[str, list[str]], agent,
                            approved: dict[str, ColumnMap] | None = None
                            ) -> tuple[list[ColumnMap], list[dict], list[Warning]]:
    """Map the header; the agent sees only the column name and up to 3 masked samples (D24)."""
    def samples(column: str) -> list[str]:
        index = header.index(column)
        values = []
        for row in rows:
            value = remove_control(row[index])[0].strip() if index < len(row) else ""
            if value:
                values.append(mask(value))
            if len(values) == 3:
                break
        return values

    try:
        maps, proposals = map_header(header, dictionary,
                                     lambda column, taken: agent.propose(column, samples(column)), approved)
    except RunError:
        raise
    except Exception:  # D25: the run must not depend on the agent
        maps, proposals = map_header(header, dictionary, None, approved)
        return maps, proposals, [Warning(None, None, "MAPPING_AGENT_FALLBACK")]
    return maps, proposals, []


def resolve_mapping(header: list[str], rows: list[list[str]], dictionary_path: Path, output: Path,
                    input_name: str, agent, approve: Path | None, now_utc: datetime
                    ) -> tuple[list[ColumnMap], list[Warning]]:
    """Whole mapping step of a run: approvals, dictionary, agent; stops with MAPPING_PENDING when needed."""
    approved = apply_approval(approve, header, dictionary_path) if approve else {}
    dictionary = load_dictionary(dictionary_path)
    maps, proposals, warnings = map_header_with_samples(header, rows, dictionary, agent, approved)
    if any(p["score"] >= 60 for p in proposals):
        path = write_proposal(output, input_name, proposals, now_utc)
        raise RunError("MAPPING_PENDING",
                       f"Mapping proposal written to {path}; approve it and run again with --approve", STAGE)
    return maps, warnings + mapping_warnings(maps)


def write_proposal(output: Path, input_name: str, proposals: list[dict], now_utc: datetime) -> Path:
    proposal_id = now_utc.strftime("proposal_%Y-%m-%d_%H%M%SZ")
    folder = Path(output) / "mapping_proposals"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{proposal_id}.json"
    content = {"schema_version": 1, "proposal_id": proposal_id, "input_file": input_name, "proposals": proposals}
    path.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def apply_approval(path: Path, header: list[str], dictionary_path: Path) -> dict[str, ColumnMap]:
    """Read the analyst's decisions; save approved and changed mappings in the dictionary."""
    try:
        proposals = json.loads(Path(path).read_text(encoding="utf-8"))["proposals"]
    except (OSError, ValueError, KeyError, TypeError):
        raise RunError("USAGE", f"Wrong arguments: --approve file cannot be read: {path}", "start") from None
    dictionary = load_dictionary(dictionary_path)
    approved: dict[str, ColumnMap] = {}
    for p in proposals:
        column, decision = p.get("column"), (p.get("decision") or "").strip().lower()
        if column not in header:
            continue
        if decision == "reject":
            approved[column] = ColumnMap(column, None, "passed_through")
            continue
        if decision in ("approve", "change"):
            field = p.get("field") if decision == "approve" else (p.get("use_field") or "").strip()
            if field not in FIELDS:
                raise RunError("USAGE", f"Wrong arguments: unknown field '{field}' for column {column}", "start")
            approved[column] = ColumnMap(column, field, "approved")
            if match_key(column) not in {match_key(n) for n in dictionary[field]}:
                dictionary[field].append(column)
            continue
        if (p.get("score") or 0) >= 60:
            raise RunError("MAPPING_PENDING",
                           f"Mapping proposal {path} has no decision for column {column}; approve it and run again",
                           STAGE)
    Path(dictionary_path).write_text(json.dumps(dictionary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return approved
