"""Stage 3, write: the five output files, written into the temporary folder (spec section 8)."""
import csv
import json
from collections import Counter
from pathlib import Path

from ingest.codes import MESSAGES
from ingest.models import ColumnMap, Duplicate, Outcome, Rejected, Warning
from ingest.rows import OUTPUT_COLUMNS

SCHEMA_VERSION = 1
REJECTED_COLUMNS = ["source_record_number", "reason_codes", "reason_text", "original_row"]
WARNING_COLUMNS = ["source_record_number", "field", "code", "message"]
DUPLICATE_COLUMNS = ["card_number", "source_record_number", "last_interaction_at", "kept_record_number", "reason"]


def canonical_columns(maps: list[ColumnMap]) -> list[str]:
    return OUTPUT_COLUMNS + [m.column for m in maps if m.field is None]


def _write_csv(path: Path, header: list[str], rows) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def write_canonical(temp: Path, canonical: list[dict], maps: list[ColumnMap]) -> None:
    columns = canonical_columns(maps)
    _write_csv(temp / "canonical_customers.csv", columns, ([row.get(c, "") for c in columns] for row in canonical))


def write_rejected(temp: Path, rejected: list[Rejected]) -> None:
    _write_csv(temp / "rejected_rows.csv", REJECTED_COLUMNS,
               ([r.record, ";".join(r.codes), ";".join(MESSAGES[c] for c in r.codes), r.original] for r in rejected))


def write_warnings(temp: Path, warnings: list[Warning]) -> None:
    _write_csv(temp / "warnings.csv", WARNING_COLUMNS,
               (["" if w.record is None else w.record, w.field or "", w.code, MESSAGES[w.code]] for w in warnings))


def write_duplicates(temp: Path, duplicates: list[Duplicate]) -> None:
    _write_csv(temp / "duplicates.csv", DUPLICATE_COLUMNS,
               ([d.card_number, d.record, d.last_interaction_at, d.kept_record, d.reason] for d in duplicates))


def write_summary(temp: Path, summary: dict) -> None:
    (temp / "run_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_outputs(temp: Path, outcome: Outcome, maps: list[ColumnMap], summary: dict) -> None:
    write_canonical(temp, outcome.canonical, maps)
    write_rejected(temp, outcome.rejected)
    write_warnings(temp, outcome.warnings)
    write_duplicates(temp, outcome.duplicates)
    write_summary(temp, summary)


def _pct(part: int, whole: int) -> float:
    return round(100 * part / whole, 2) if whole else 0.0


def build_summary(*, run_id: str, run_started_at: str, export_date: str, input_name: str, rows_received: int,
                  maps: list[ColumnMap], outcome: Outcome, stages: dict, total_ms: float,
                  total_memory_mb: float | None, thresholds: dict) -> dict:
    canonical = len(outcome.canonical)
    no_contact = sum("NO_CONTACT_CHANNEL" in r["ineligibility_reasons"] for r in outcome.canonical)
    reasons = Counter(code for r in outcome.canonical for code in r["ineligibility_reasons"].split(";") if code)
    observed = {"missing_contact_pct": _pct(no_contact, canonical), "rejection_pct": _pct(len(outcome.rejected), rows_received)}
    eligible = sum(r["eligible_for_campaign"] == "yes" for r in outcome.canonical)
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "run_started_at": run_started_at,
        "export_date": export_date,
        "input": {"file": input_name, "rows_received": rows_received},
        "mapping": [{"column": m.column, "field": m.field, "source": m.source} for m in maps],
        "destinations": {"canonical": canonical, "rejected": len(outcome.rejected),
                         "duplicate_losing": len(outcome.duplicates),
                         "reconciled": canonical + len(outcome.rejected) + len(outcome.duplicates) == rows_received},
        "eligibility": {"eligible": eligible, "not_eligible": canonical - eligible, "reasons": dict(reasons)},
        "warnings": {"total": len(outcome.warnings), "by_code": dict(Counter(w.code for w in outcome.warnings))},
        "stages": stages,
        "total_duration_ms": total_ms,
        "total_memory_mb": total_memory_mb,
        "thresholds": thresholds,
        "observed": observed,
        "flags": {"source_probably_broke": observed["missing_contact_pct"] > thresholds["missing_contact_pct"],
                  "rejection_rate_high": observed["rejection_pct"] > thresholds["rejection_pct"]},
    }
