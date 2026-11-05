"""Stage 1, read: file checks, delimiter, header and strict record reading (spec section 4)."""
import csv
import io
import re
from pathlib import Path

from ingest.errors import RunError
from ingest.models import RawRecord, ReadResult, Rejected, Warning
from ingest.text import remove_control

STAGE = "read"
_NEWLINE = re.compile(r"\r\n|\r|\n")


def read_file(path: Path) -> ReadResult:
    data = _load(path)
    text = _decode(data)
    delimiter = _detect_delimiter(_NEWLINE.split(text, 1)[0])
    return _read_records(text, delimiter)


def _load(path: Path) -> bytes:
    path = Path(path)
    if not path.exists():
        raise RunError("INPUT_NOT_FOUND", f"Input file not found: {path}", STAGE)
    try:
        data = path.read_bytes()
    except OSError as exc:
        reason = "a directory" if path.is_dir() else (exc.strerror or type(exc).__name__)
        raise RunError("INPUT_UNREADABLE", f"Input file cannot be read: {path} ({reason})", STAGE) from None
    if not data:
        raise RunError("INPUT_EMPTY", f"Input file is empty (0 bytes): {path}", STAGE)
    return data


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        line = len(_NEWLINE.findall(data[:exc.start].decode("utf-8", errors="replace"))) + 1
        where = "the header" if line == 1 else f"record {line - 1}"
        raise RunError("INVALID_UTF8", f"Input is not valid UTF-8 (near {where}); save the file as UTF-8",
                       STAGE) from None


def _detect_delimiter(header_line: str) -> str:
    counts = {d: len(next(csv.reader([header_line], delimiter=d))) for d in (",", ";")}
    if counts[","] == counts[";"]:
        if counts[","] > 1 or any(ch in header_line for ch in "\t|"):
            raise RunError("UNSUPPORTED_DELIMITER",
                           "Delimiter not supported; accepted delimiters are comma and semicolon", STAGE)
        return ","
    return max(counts, key=counts.get)


def _clean_header(cells: list[str]) -> tuple[list[str], list[Warning]]:
    if not any(re.search(r"[^\W\d_]", c) for c in cells) or any(re.fullmatch(r"\d{16}", c.strip()) for c in cells):
        raise RunError("NO_HEADER", "The first line does not look like a header", STAGE)
    header, warnings = [], []
    for position, cell in enumerate(cells, start=1):
        name, removed = remove_control(cell)
        name = name.strip() or f"column_{position}"
        if removed:
            warnings.append(Warning(None, name, "CONTROL_CHARACTER_REMOVED"))
        header.append(name)
    return header, warnings


def _read_records(text: str, delimiter: str) -> ReadResult:
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    header, warnings = _clean_header(next(reader))
    records: list[RawRecord] = []
    rejected: list[Rejected] = []
    number = 0
    for cells in reader:
        if not cells:
            continue
        number += 1
        records.append(RawRecord(number, reader.line_num, cells, delimiter.join(cells)))
    if number == 0:
        raise RunError("NO_DATA_ROWS", "Input has a header but no data rows", STAGE)
    return ReadResult(header, delimiter, records, rejected, warnings, number)
