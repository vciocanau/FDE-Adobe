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


MAX_RECORD_LINES = 5


def _read_records(text: str, delimiter: str) -> ReadResult:
    csv.field_size_limit(2**31 - 1)
    lines = _NEWLINE.split(text)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    header, warnings = _clean_header(next(reader))
    width = len(header)
    records: list[RawRecord] = []
    rejected: list[Rejected] = []
    number = 0
    while True:
        start = reader.line_num + 1
        try:
            cells = next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            if "unexpected end of data" in str(exc):
                raise _unclosed(start) from None
            number += 1
            rejected.append(Rejected(number, ["BAD_QUOTING"], _original(lines, start, reader.line_num)))
            continue
        span = reader.line_num - start + 1
        if not cells:
            continue
        if span > MAX_RECORD_LINES:
            raise _unclosed(start)
        number += 1
        original = _original(lines, start, reader.line_num)
        if span > 1:
            warnings.append(Warning(number, None, "MULTILINE_RECORD"))
        if len(cells) > width:
            if any(c.strip() for c in cells[width:]):
                rejected.append(Rejected(number, ["EXTRA_CELLS"], original))
                continue
            cells = cells[:width]
            warnings.append(Warning(number, None, "TRAILING_EMPTY_CELLS"))
        elif len(cells) < width:
            cells = cells + [""] * (width - len(cells))
            warnings.append(Warning(number, None, "SHORT_ROW"))
        records.append(RawRecord(number, start, cells, original))
    if number == 0:
        raise RunError("NO_DATA_ROWS", "Input has a header but no data rows", STAGE)
    return ReadResult(header, delimiter, records, rejected, warnings, number)


def _unclosed(line: int) -> RunError:
    return RunError("UNCLOSED_QUOTE", f"A quoted field is never closed; the broken record starts on line {line}",
                    STAGE)


def _original(lines: list[str], first: int, last: int) -> str:
    return remove_control("\n".join(lines[first - 1:last]))[0]
