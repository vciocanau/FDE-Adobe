"""Stage 4, verify: re-read the written files, reconcile totals, publish by renaming (spec 7.4, 8, D17)."""
import csv
import json
import os
import shutil
from pathlib import Path

from ingest.errors import RunError
from ingest.models import Warning
from ingest.writer import DUPLICATE_COLUMNS, REJECTED_COLUMNS, WARNING_COLUMNS

STAGE = "verify"


def _fail(detail: str) -> RunError:
    return RunError("VERIFY_FAILED", f"Verification failed: {detail}; nothing was published", STAGE)


def _count(path: Path, expected_header: list[str] | None) -> int:
    try:
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise _fail(f"{path.name} cannot be read back ({exc})") from None
    if not rows or (expected_header is not None and rows[0] != expected_header):
        raise _fail(f"{path.name} has an unexpected header")
    return len(rows) - 1


def verify(temp: Path, rows_received: int) -> None:
    try:
        summary = json.loads((temp / "run_summary.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _fail(f"run_summary.json cannot be read back ({exc})") from None
    canonical = _count(temp / "canonical_customers.csv", None)
    rejected = _count(temp / "rejected_rows.csv", REJECTED_COLUMNS)
    _count(temp / "warnings.csv", WARNING_COLUMNS)
    duplicates = _count(temp / "duplicates.csv", DUPLICATE_COLUMNS)
    dest = summary.get("destinations", {})
    if (dest.get("canonical"), dest.get("rejected"), dest.get("duplicate_losing")) != (canonical, rejected, duplicates):
        raise _fail("file row counts differ from the summary")
    if canonical + rejected + duplicates != rows_received:
        raise _fail(f"{rows_received} rows received but {canonical + rejected + duplicates} have a destination")


def publish(temp: Path, run_folder: Path) -> None:
    if run_folder.exists():
        raise RunError("RUN_FOLDER_EXISTS", f"Run folder already exists: {run_folder}; nothing was overwritten", "write")
    os.rename(temp, run_folder)


def discard(temp: Path, debug: bool, failed_name: str) -> None:
    if not temp.exists():
        return
    if debug:
        os.rename(temp, temp.parent / failed_name)
    else:
        shutil.rmtree(temp, ignore_errors=True)


def _posix() -> bool:
    return os.name == "posix"


def restrict_permissions(folder: Path) -> list[Warning]:
    """Spec 8 (D26): run folder and files readable only by their owner where the system supports it."""
    if not _posix():
        return [Warning(None, None, "PERMISSIONS_SKIPPED")]
    for path in folder.iterdir():
        path.chmod(0o600)
    folder.chmod(0o700)
    return []
