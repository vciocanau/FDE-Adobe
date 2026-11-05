# CRM Loyalty Profile Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A command-line program that reads one CRM customer-profile CSV export, cleans and validates it, and publishes a canonical customer table with export-time campaign eligibility, plus rejected rows, duplicates, warnings and a run summary.

**Architecture:** One Python package, `ingest`, with one module per responsibility: reading, header mapping, field rules, row processing, writing and verifying, operations (time, memory, log), and the command line. Each stage passes plain dataclasses to the next. All results are held in memory (D16). Files are written into a temporary folder and published by renaming it only after verification.

**Tech Stack:** Python standard library only (`csv`, `json`, `unicodedata`, `datetime`, `zoneinfo`, `difflib`, `ctypes`, `resource`, `logging`, `argparse`, `unittest`).

**Spec:** `docs/specification/specification.md` (sections and AC numbers below refer to it). Assumptions and decisions (A1–A10, D1–D30): `docs/brainstorming/brainstorming.md`.

## Global Constraints

- Python 3.11 or later; no third-party package at run time or in tests (D18). Tests use `unittest`: `python -m unittest -v`.
- Command: `python -m ingest run --input <file.csv>`, arguments as in spec section 3; exit codes 0–5 as in spec section 3.
- Every code used anywhere is a name from spec section 9; no new code without adding it to section 9 first.
- Output CSV files: UTF-8 without a BOM, comma delimiter, header row even when empty, minimal quoting, codes inside one cell separated by `;`.
- Output files: `canonical_customers.csv`, `rejected_rows.csv`, `warnings.csv`, `duplicates.csv`, `run_summary.json`; run folder `run_YYYY-MM-DD_HHMMSSZ` (UTC); failed folder with `--debug` `failed_YYYY-MM-DD_HHMMSSZ`; log `<output>/logs/run_YYYY-MM-DD_HHMMSSZ.log`; proposals `<output>/mapping_proposals/proposal_YYYY-MM-DD_HHMMSSZ.json`.
- No traceback ever reaches the operator; every stop prints `ERROR <CODE> [stage <name>] <message>`.
- No personal value (card, name, email, phone) in the log (spec 10.1).
- Control characters: Unicode category Cc except U+0009, U+000A, U+000D; removed from every value, header name and `original_row` before any rule (spec 6.1).
- Documents and code comments in English; documents impersonal.
- Test expectations come from the spec and are checked against a case worked out by hand before the code exists.
- Every test method's docstring starts with the acceptance case it proves, for example `"""AC-43: the newer row withdraws consent and wins."""`; a test that proves no AC names the Review Focus line or the spec section instead.
- One commit per task at least; the message starts with the task number, for example `Task 10: row processing, duplicates and eligibility`.
- Written CSV files end every line with LF (`\n`) on every operating system.

## Tiers

| Tier | Tasks | Rule |
| --- | --- | --- |
| Essential | 1–14, 18 | Without these there is no deliverable |
| Important | 15, 16, 17, 19 | Done in this order if time allows; whatever is not done is listed in the README as not implemented |
| Optional | not planned as tasks | A separate file of assumptions to confirm, a written extrapolation report beyond the README figures |

Windows memory reading is essential (Task 12). macOS memory reading is a step inside Task 12 marked important.

## Review Focus

1. A cell longer than the `csv` module's default field limit (131,072 characters): the record is read, not a crash and not a silent cut. Test in Task 7.
2. `--input` pointing at a folder: `INPUT_UNREADABLE`, exit 2. Test in Task 13.
3. `--output` pointing at an existing file: `OUTPUT_NOT_WRITABLE`, exit 2, nothing written. Test in Task 13.
4. A card column present but empty in every row: every row rejected, `REJECTION_RATE_HIGH` (when Task 15 is done), five files still published, totals reconcile. Test in Task 10 (without the threshold) and Task 15.
5. A status cell holding only spaces (`"   "`): `unknown` with its warning, not a crash and not `yes`. Test in Task 5.

---

## File Structure

```
ingest/
  __init__.py
  __main__.py      entry point: calls cli.main()
  cli.py           arguments, run orchestration, exit codes, operator messages
  errors.py        RunError and the run-error table (code, exit, stage)
  codes.py         plain-text messages for every rejection, duplicate and warning code
  models.py        dataclasses shared by all stages
  text.py          control-character removal, name normalization for matching
  reader.py        file checks, delimiter, header, strict record reading
  fields.py        one cleaning function per field (spec 6.2–6.10)
  agent.py         simulated mapping agent and sample masking
  mapping.py       dictionary, header mapping, proposal file, approvals
  rows.py          row processing: rejection, duplicates, eligibility, totals
  writer.py        writing the five files into the temporary folder
  publish.py       verification, publishing, failed-folder handling, permissions
  ops.py           stage timer, process peak memory, total memory, memory guard, log setup
mappings/synonyms.json        starting dictionary (spec 5)
tools/generate_synthetic.py   synthetic CRM export generator
tests/                        one test module per ingest module, plus test_cli.py and test_volume.py
tests/fixtures/small.csv      one small hand-written CSV file (Task 13); other tests write their input into a temporary folder
docs/brainstorming/brainstorming.md
docs/specification/specification.md
docs/plan/2026-11-05-ingest-plan.md
docs/ai-log.md
README.md  CLAUDE.md  AGENTS.md  .gitignore
```

## Shared Interfaces (`ingest/models.py`)

Defined in Task 1; every later task uses these names.

```python
@dataclass
class Warning:
    record: int | None      # source_record_number, None for run warnings
    field: str | None       # field or column name, None for run warnings
    code: str

@dataclass
class RawRecord:
    number: int             # source_record_number, from 1, header not counted
    line: int               # physical line where the record starts
    cells: list[str]
    original: str           # the record as read, control characters removed

@dataclass
class Rejected:
    record: int
    codes: list[str]
    original: str

@dataclass
class ReadResult:
    header: list[str]
    delimiter: str
    records: list[RawRecord]
    rejected: list[Rejected]
    warnings: list[Warning]
    rows_received: int

@dataclass
class ColumnMap:
    column: str             # header name after control-character removal and suffixing
    field: str | None       # canonical field, None when passed through
    source: str             # "dictionary" | "approved" | "passed_through"

@dataclass
class FieldResult:
    value: str              # cleaned value, "" when empty or emptied
    codes: list[str]        # warning codes, or one rejection code for the card

@dataclass
class Duplicate:
    card_number: str
    record: int
    last_interaction_at: str
    kept_record: int
    reason: str

@dataclass
class Outcome:
    canonical: list[dict[str, str]]   # canonical columns, then pass-through columns
    rejected: list[Rejected]
    duplicates: list[Duplicate]
    warnings: list[Warning]
```

`errors.RunError(code: str, message: str, stage: str, detail: str | None = None)` carries `exit_code` looked up from the table in Task 1.

Canonical fields, in output order: `card_number, first_name, last_name, email, phone, app_installed, consent, subscription, last_interaction_at, last_purchase_at, last_purchase_amount, eligible_for_campaign, ineligibility_reasons, source_record_number`.

---

### Task 1: Project skeleton, models, codes, control characters [Essential]

**Files:**
- Create: `ingest/__init__.py`, `ingest/__main__.py`, `ingest/models.py`, `ingest/errors.py`, `ingest/codes.py`, `ingest/text.py`, `.gitignore`, `tests/__init__.py`, `tests/test_text.py`, `tests/test_errors.py`

**Interfaces:**
- Produces: the dataclasses above; `RunError`; `codes.MESSAGES: dict[str, str]` (every rejection, duplicate and warning code of spec 9 with its plain text); `text.remove_control(value: str) -> tuple[str, bool]`; `text.match_key(name: str) -> str` (spec 5 normalization).

- [ ] **Step 1: Write the failing tests**

```python
class TextTests(unittest.TestCase):
    def test_removes_cc_but_keeps_tab_lf_cr(self):
        self.assertEqual(remove_control("Ghe\x01orghe\x7f"), ("Gheorghe", True))
        self.assertEqual(remove_control("a\tb\nc\rd"), ("a\tb\nc\rd", False))
    def test_match_key(self):
        for name in ["Loyalty Card", "loyalty_card", "LOYALTY-CARD", " loyalty.card "]:
            self.assertEqual(match_key(name), "loyaltycard")
        self.assertEqual(match_key("Ultima_Interacțiune"), "ultimainteractiune")

class ErrorTests(unittest.TestCase):
    def test_exit_codes(self):
        expected = {"USAGE": 2, "INPUT_NOT_FOUND": 2, "INPUT_UNREADABLE": 2, "OUTPUT_NOT_WRITABLE": 2,
                    "RUN_FOLDER_EXISTS": 2, "INPUT_EMPTY": 1, "NO_DATA_ROWS": 1, "NO_HEADER": 1,
                    "UNSUPPORTED_DELIMITER": 1, "INVALID_UTF8": 1, "UNCLOSED_QUOTE": 1,
                    "CARD_COLUMN_MISSING": 1, "FIELD_MAPPED_TWICE": 1, "MAPPING_PENDING": 3,
                    "MEMORY_LIMIT": 4, "VERIFY_FAILED": 5, "INTERNAL_ERROR": 5}
        for code, exit_code in expected.items():
            self.assertEqual(RunError(code, "m", "read").exit_code, exit_code)
    def test_every_section9_code_has_a_message(self):
        for code in ["CARD_EMPTY", "CARD_INVALID", "EXTRA_CELLS", "BAD_QUOTING",
                     "LOST_OLDER_TIMESTAMP", "LOST_INVALID_TIMESTAMP", "LOST_TIE_LATER_ROW_WINS",
                     "SHORT_ROW", "CONTROL_CHARACTER_REMOVED", "MULTILINE_RECORD", "TRAILING_EMPTY_CELLS"]:
            self.assertIn(code, MESSAGES)
```

The second test lists a sample; the implementer copies the full lists from spec section 9 into `MESSAGES`.

- [ ] **Step 2: Run `python -m unittest tests.test_text tests.test_errors -v`.** Expected: FAIL (import error).
- [ ] **Step 3: Implement `models.py`, `errors.py`, `codes.py`, `text.py`.** `match_key`: strip, lowercase, NFKD and drop combining marks, drop spaces, `-`, `.`, `_`. `.gitignore`: `runs/`, `__pycache__/`, `*.pyc`, `tests/_tmp/`, `synthetic_*.csv`.
- [ ] **Step 4: Run the same command.** Expected: PASS.
- [ ] **Step 5: Commit** `project skeleton, shared models, codes and control-character helper`.

### Task 2: Card and names [Essential]

**Files:** Create `ingest/fields.py`, `tests/test_fields.py`.

**Interfaces:**
- Consumes: `text.remove_control`.
- Produces: `clean_card(raw: str) -> FieldResult` (codes: `[]`, or one of `CARD_EMPTY`, `CARD_INVALID`, plus `CONTROL_CHARACTER_REMOVED` when a character was removed); `clean_name(raw: str) -> FieldResult`.

- [ ] **Step 1: Write the failing tests** (AC-26 to AC-31)

```python
def test_card(self):
    self.assertEqual(clean_card("12345 678901234 56").value, "1234567890123456")
    self.assertEqual(clean_card("1234-5678-9012-3456").value, "1234567890123456")
    self.assertEqual(clean_card("0012345678901234").value, "0012345678901234")
    for raw, code in [("1234 5678", "CARD_INVALID"), ("12345678901234AB", "CARD_INVALID"),
                      ("", "CARD_EMPTY"), ("1.23457E+15", "CARD_INVALID"),
                      ("１２３４５６７８９０１２３４５６", "CARD_INVALID")]:
        self.assertIn(code, clean_card(raw).codes)
    r = clean_card("12345678\x0190123456")
    self.assertEqual((r.value, r.codes), ("1234567890123456", ["CONTROL_CHARACTER_REMOVED"]))
    self.assertIn("CARD_INVALID", clean_card("1234567\x0190123456").codes)
def test_names(self):
    self.assertEqual(clean_name("Gheorghe\x01").value, "Gheorghe")
    self.assertEqual(clean_name("Ştefan Ţurcanu").value, clean_name("Ștefan Țurcanu").value)
    self.assertEqual(clean_name("  Ana   Maria ").value, "Ana Maria")
    self.assertEqual(clean_name("Ioané").value, "Ioané")   # NFC
    self.assertEqual(clean_name("").codes, [])
    self.assertEqual(clean_name("\x01\x02").codes, ["CONTROL_CHARACTER_REMOVED"])
```

- [ ] **Step 2: Run `python -m unittest tests.test_fields -v`.** Expected: FAIL.
- [ ] **Step 3: Implement both functions in `ingest/fields.py`.** Card: after control removal, remove every whitespace character and `-`; valid only if `re.fullmatch(r"[0-9]{16}", value, re.ASCII)`. Names: collapse with `" ".join(value.split())`, `unicodedata.normalize("NFC", ...)`, map `ş ţ Ş Ţ` to `ș ț Ș Ț`.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `card and name rules`.

### Task 3: Phone and email [Essential]

**Files:** Modify `ingest/fields.py`, `tests/test_fields.py`.

**Interfaces:** Produces `clean_phone(raw: str) -> FieldResult`, `clean_email(raw: str) -> FieldResult`.

- [ ] **Step 1: Write the failing tests** (AC-32, AC-33)

```python
def test_phone(self):
    for raw in ["0722123456", "0040722123456", "+40722123456", "0722 123 456", "(0722)-123.456"]:
        self.assertEqual(clean_phone(raw).value, "+40722123456")
    r = clean_phone("722123456")
    self.assertEqual((r.value, r.codes), ("+40722123456", ["PHONE_LEADING_ZERO"]))
    self.assertEqual(clean_phone("+4915112345678").value, "+4915112345678")
    self.assertEqual(clean_phone("12345").codes, ["PHONE_INVALID"])
    self.assertEqual(clean_phone("").codes, [])
def test_email(self):
    self.assertEqual(clean_email(" Ana@Example.COM ").value, "ana@example.com")
    for raw in ["ana @example.com", "ana@@example.com", "ana@example"]:
        r = clean_email(raw)
        self.assertEqual((r.value, r.codes), ("", ["EMAIL_INVALID"]))
```

- [ ] **Step 2: Run the tests.** Expected: FAIL.
- [ ] **Step 3: Implement.** Phone order exactly as spec 6.4 steps 2–7; digit count checked on the normalized number without the `+`. Email exactly as spec 6.5.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `phone and email rules`.

### Task 4: Dates [Essential]

**Files:** Modify `ingest/fields.py`, `tests/test_fields.py`.

**Interfaces:** Produces `parse_timestamp(raw: str, run_time: datetime) -> FieldResult` (value in the stored ISO form) and `timestamp_sort_key(value: str) -> datetime` (aware datetime; a date alone is 00:00:00 local time). `run_time` is an aware local datetime.

- [ ] **Step 1: Write the failing tests** (AC-34, AC-35)

```python
RUN = datetime(2026, 11, 5, 12, 0, tzinfo=timezone(timedelta(hours=2)))
def test_dates(self):
    for raw in ["2026-11-04", "04.11.2026", "04/11/2026"]:
        self.assertEqual(parse_timestamp(raw, RUN).value, "2026-11-04")
    self.assertEqual(parse_timestamp("2026-11-04 14:30", RUN).value, "2026-11-04T14:30:00")
    self.assertEqual(parse_timestamp("04.11.2026T14:30:15", RUN).value, "2026-11-04T14:30:15")
    self.assertEqual(parse_timestamp("2026-11-04T14:30:00+02:00", RUN).value, "2026-11-04T14:30:00+02:00")
    self.assertEqual(parse_timestamp("2026-11-04T12:30:00Z", RUN).value, "2026-11-04T12:30:00+00:00")
    for raw in ["11/13/2026", "13.13.2026", "31.02.2026", "abc"]:
        self.assertEqual(parse_timestamp(raw, RUN).codes, ["TIMESTAMP_UNREADABLE"])
    self.assertEqual(parse_timestamp("0001-01-01T00:00:00+01:00", RUN).codes, ["TIMESTAMP_OUT_OF_RANGE"])
    self.assertEqual(parse_timestamp("2026-11-06", RUN).codes, ["TIMESTAMP_IN_FUTURE"])
    self.assertEqual(parse_timestamp("", RUN).codes, [])
```

- [ ] **Step 2: Run the tests.** Expected: FAIL.
- [ ] **Step 3: Implement.** Date patterns `YYYY-MM-DD`, `DD.MM.YYYY`, `DD/MM/YYYY`; optional time `HH:MM` or `HH:MM:SS` after a space or `T`; `Z` or `±HH:MM` only after an ISO date. Convert to UTC inside `try`, catching `OverflowError` and `ValueError` → `TIMESTAMP_OUT_OF_RANGE`. A value without a zone gets the local zone of the machine for comparison only; the stored value keeps no offset.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `date and timestamp rules`.

### Task 5: Status values and amount [Essential]

**Files:** Modify `ingest/fields.py`, `tests/test_fields.py`.

**Interfaces:** Produces `clean_consent(raw) -> FieldResult` (`yes|no|unknown`), `clean_subscription(raw) -> FieldResult` (`active|inactive|unknown`), `clean_app(raw) -> FieldResult` (`yes|no|unknown`), `clean_amount(raw) -> FieldResult`, and `STATUS_VALUES: frozenset[str]` (every listed value of 6.7–6.9, lowercase, used by the masking in Task 9).

- [ ] **Step 1: Write the failing tests** (AC-37 to AC-39, Review Focus 5)

```python
def test_consent(self):
    for raw in ["Da", " YES ", "Opt-In", "opt in", "o.k", "1"]:
        self.assertEqual(clean_consent(raw).value, "yes")
    for raw in ["nu", "Nu Doresc", "nu-doresc", "OPTOUT", "Retras", "0"]:
        self.assertEqual(clean_consent(raw).value, "no")
    for raw in ["", "   ", "nu accept", "maybe"]:
        r = clean_consent(raw)
        self.assertEqual((r.value, r.codes), ("unknown", ["CONSENT_UNKNOWN"]))
def test_subscription(self):
    self.assertEqual(clean_subscription(" Activ ").value, "active")
    self.assertEqual(clean_subscription("INACTIV").value, "inactive")
    self.assertEqual(clean_subscription("opt-in").codes, ["SUBSCRIPTION_UNKNOWN"])   # no separator folding
def test_app(self):
    self.assertEqual(clean_app("Installed").value, "yes")
    self.assertEqual(clean_app("").codes, ["APP_INSTALLED_UNKNOWN"])
def test_amount(self):
    for raw, value in [("12.50", "12.50"), ("12,50", "12.50"), (" 12.50 ", "12.50"), ("12,5", "12.5")]:
        self.assertEqual(clean_amount(raw).value, value)
    for raw in ["-12.50", "0", "0.00", "12 lei", "1,234", "1.234,50", "abc"]:
        self.assertEqual(clean_amount(raw).codes, ["PURCHASE_AMOUNT_INVALID"])
```

- [ ] **Step 2: Run the tests.** Expected: FAIL.
- [ ] **Step 3: Implement** with the exact lists from spec 6.7–6.9. Consent comparison removes spaces, hyphens and dots; subscription and app only strip and lowercase. Amount: `re.fullmatch(r"[0-9]+([.,][0-9]{1,2})?", value, re.ASCII)`, then replace `,` with `.`, reject if the value equals zero.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `consent, subscription, app installed and amount rules`.

### Task 6: Reader, file level [Essential]

**Files:** Create `ingest/reader.py`, `tests/test_reader.py` (inputs are written by the tests into a temporary folder).

**Interfaces:**
- Produces: `read_file(path: Path) -> ReadResult`, raising `RunError` with `INPUT_NOT_FOUND`, `INPUT_UNREADABLE`, `INPUT_EMPTY`, `INVALID_UTF8`, `NO_HEADER`, `UNSUPPORTED_DELIMITER`, `NO_DATA_ROWS`.

- [ ] **Step 1: Write the failing tests** (AC-01 to AC-09)

```python
def test_missing_file(self):
    with self.assertRaises(RunError) as e: read_file(self.tmp / "nope.csv")
    self.assertEqual(e.exception.code, "INPUT_NOT_FOUND")
def test_empty_and_header_only(self):
    self.assertRaisesCode("INPUT_EMPTY", b"")
    self.assertRaisesCode("NO_DATA_ROWS", b"card_number,email\n")
    self.assertRaisesCode("NO_DATA_ROWS", b"card_number,email\n\n\n")
def test_no_header(self):
    self.assertRaisesCode("NO_HEADER", b"1234567890123456,a@b.ro\n")
def test_delimiters(self):
    self.assertEqual(self.read(b"card_number;email\n1234567890123456;a@b.ro\n").delimiter, ";")
    self.assertRaisesCode("UNSUPPORTED_DELIMITER", b"card_number\temail\n1\t2\n")
def test_utf8(self):
    self.assertRaisesCode("INVALID_UTF8", b"card_number,em\xffail\n1,2\n")
    self.assertRaisesCode("INVALID_UTF8", b"card_number,email\n1,2\n" * 50 + b"3,\xfe\n")
def test_bom_and_line_endings(self):
    body = "card_number,email\n1234567890123456,a@b.ro\n"
    base = self.read(body.encode())
    self.assertEqual(self.read(b"\xef\xbb\xbf" + body.encode()).header, ["card_number", "email"])
    for nl in ["\r\n", "\r"]:
        self.assertEqual(self.read(body.replace("\n", nl).encode()).records[0].cells, base.records[0].cells)
```

`assertRaisesCode` and `read` are small helpers in the test class that write bytes to a temporary file.

- [ ] **Step 2: Run `python -m unittest tests.test_reader -v`.** Expected: FAIL.
- [ ] **Step 3: Implement the file-level part of `read_file`.** Read bytes; zero bytes → `INPUT_EMPTY`; decode with `utf-8-sig`, on `UnicodeDecodeError` report the record near the failing byte; detect the delimiter from the header line by counting cells with `,` and `;` (tie → `UNSUPPORTED_DELIMITER`; one cell only and a tab or `|` present → `UNSUPPORTED_DELIMITER`); `NO_HEADER` when no header cell has a letter or one cell is 16 digits; empty header cells become `column_<position>`; duplicate unknown names get `_2`, `_3`. Remove control characters from header names (warning with the column in `field`).
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `reader file checks, delimiter and header`.

### Task 7: Reader, records [Essential]

**Files:** Modify `ingest/reader.py`, `tests/test_reader.py`.

**Interfaces:** `read_file` now fills `records`, `rejected` (`EXTRA_CELLS`, `BAD_QUOTING`), `warnings` (`SHORT_ROW`, `TRAILING_EMPTY_CELLS`, `MULTILINE_RECORD`) and raises `UNCLOSED_QUOTE`. `MAX_RECORD_LINES = 5` is a module constant.

- [ ] **Step 1: Write the failing tests** (AC-10 to AC-17, Review Focus 1)

```python
H = "card_number,email,first_name\n"
def test_extra_cells(self):
    r = self.read((H + "1111222233334444,a@b.ro,Ana,\n1111222233334445,b@b.ro,Ion,X\n").encode())
    self.assertEqual([w.code for w in r.warnings], ["TRAILING_EMPTY_CELLS"])
    self.assertEqual((r.rejected[0].record, r.rejected[0].codes), (2, ["EXTRA_CELLS"]))
def test_short_row(self):
    r = self.read((H + "1111222233334444,a@b.ro\n").encode())
    self.assertEqual((r.records[0].cells, r.warnings[0].code), (["1111222233334444", "a@b.ro", ""], "SHORT_ROW"))
def test_bad_quoting_continues(self):
    r = self.read((H + '1111222233334444,a@b.ro,"abc"def\n1111222233334445,b@b.ro,Ion\n').encode())
    self.assertEqual(r.rejected[0].codes, ["BAD_QUOTING"]); self.assertEqual(len(r.records), 1)
def test_multiline(self):
    r = self.read((H + '1111222233334444,a@b.ro,"Ana\nMaria"\n').encode())
    self.assertEqual(r.records[0].cells[2], "Ana\nMaria"); self.assertEqual(r.warnings[0].code, "MULTILINE_RECORD")
def test_unclosed_quote_names_start_line(self):
    with self.assertRaises(RunError) as e:
        self.read((H + '1111222233334444,a@b.ro,"unclosed\n1111222233334445,b@b.ro,next\n').encode())
    self.assertEqual(e.exception.code, "UNCLOSED_QUOTE"); self.assertIn("line 2", e.exception.message)
def test_record_over_five_lines_stops(self):
    body = H + '1111222233334444,a@b.ro,"x\n' + "1111222233334445,b@b.ro,y\n" * 14 + 'z"\n'
    with self.assertRaises(RunError) as e: self.read(body.encode())
    self.assertEqual(e.exception.code, "UNCLOSED_QUOTE")
def test_stray_quote_inside_unquoted_field_is_text(self):
    self.assertEqual(self.read((H + '1111222233334444,a@b.ro,ab"c\n').encode()).records[0].cells[2], 'ab"c')
def test_very_long_cell(self):
    self.assertEqual(len(self.read((H + "1111222233334444,a@b.ro," + "x" * 200_000 + "\n").encode()).records[0].cells[2]), 200_000)
def test_counts(self):
    r = self.read((H + "1111222233334444,a,b\n\n,,\n").encode())
    self.assertEqual(r.rows_received, 2)      # empty line skipped; ",," is a record
```

- [ ] **Step 2: Run the tests.** Expected: FAIL.
- [ ] **Step 3: Implement record reading.** Use `csv.reader(io.StringIO(text, newline=""), delimiter=..., strict=True)` and raise `csv.field_size_limit` to `sys.maxsize`-safe value. Iterate manually with `next()` so that a `csv.Error` for one record (`BAD_QUOTING`) rejects that record and reading continues; an error at end of data is `UNCLOSED_QUOTE`. Track `reader.line_num` before and after each record to get the start line and the span; span > 1 → `MULTILINE_RECORD`; span > `MAX_RECORD_LINES` → `UNCLOSED_QUOTE` naming the start line. Keep `original` as the record text re-joined with the delimiter, after control-character removal.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `strict record reading with diagnostics`.

### Task 8: Header mapping with the dictionary [Essential]

**Files:** Create `ingest/mapping.py`, `mappings/synonyms.json`, `tests/test_mapping.py`.

**Interfaces:**
- Consumes: `text.match_key`.
- Produces: `load_dictionary(path: Path) -> dict[str, list[str]]`; `map_header(header: list[str], dictionary, proposer=None) -> tuple[list[ColumnMap], list[dict]]` where the second item is the list of proposals (empty in this task); raises `CARD_COLUMN_MISSING`, `FIELD_MAPPED_TWICE`; `UNKNOWN_COLUMN` warnings are produced by `mapping_warnings(maps) -> list[Warning]`.

- [ ] **Step 1: Write the failing tests** (AC-18 to AC-20)

```python
def test_dictionary_names(self):
    maps, _ = map_header(["Loyalty Card", "E-mail", "Tel. Mobil", "Religie"], self.dictionary)
    self.assertEqual([(m.field, m.source) for m in maps],
                     [("card_number", "dictionary"), ("email", "dictionary"),
                      ("phone", "dictionary"), (None, "passed_through")])
def test_missing_card(self):
    self.assertRaisesCode("CARD_COLUMN_MISSING", ["email", "phone"])
def test_field_twice(self):
    self.assertRaisesCode("FIELD_MAPPED_TWICE", ["card", "card_number", "email"])
```

- [ ] **Step 2: Run the tests.** Expected: FAIL.
- [ ] **Step 3: Implement.** `synonyms.json` holds exactly the starting names of spec 5. Matching compares `match_key` of the header with `match_key` of every dictionary name; whole-name match only.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `header mapping with synonym dictionary and pass-through`.

### Task 9: Simulated agent, proposals and approvals [Essential]

**Files:** Create `ingest/agent.py`, `tests/test_agent.py`; modify `ingest/mapping.py`, `tests/test_mapping.py`.

**Interfaces:**
- Consumes: `fields.STATUS_VALUES`, `ColumnMap`.
- Produces: `map_header_with_samples(header: list[str], rows: list[list[str]], dictionary, agent) -> tuple[list[ColumnMap], list[dict], list[Warning]]` (maps, proposals, warnings); `mask(value: str) -> str`; `SimulatedAgent.propose(column: str, samples: list[str]) -> tuple[str | None, int, str]` (field, score, reason); `band(score: int) -> str` (`"safe"` > 90, `"caution"` 60–90, `"none"` < 60); `write_proposal(output: Path, input_name: str, proposals: list[dict], now_utc: datetime) -> Path`; `apply_approval(path: Path, header: list[str], dictionary_path: Path) -> dict[str, ColumnMap]` raising `USAGE` for an unknown `use_field` and `MAPPING_PENDING` for a proposal of 60 or more without a decision.

- [ ] **Step 1: Write the failing tests** (AC-21, AC-22, AC-24)

```python
def test_mask(self):
    self.assertEqual(mask("ion@x.ro"), "xxx@x.xx"); self.assertEqual(mask("0722 123"), "9999 999")
    self.assertEqual(mask("Da"), "Da"); self.assertEqual(mask("Activ"), "Activ")
def test_agent_sees_only_names_and_three_masked_samples(self):
    agent = RecordingAgent()
    map_header_with_samples(["NrCl", "email"], [["1234567890123456", "a@b.ro"]] * 5, self.dictionary, agent)
    self.assertEqual(agent.calls, [("NrCl", ["9999999999999999"] * 3)])
def test_bands_and_stop(self):
    self.assertEqual([band(s) for s in (94, 90, 60, 59)], ["safe", "caution", "caution", "none"])
    with self.assertRaises(RunError) as e: self.run_mapping(["NrCl", "email"])
    self.assertEqual(e.exception.code, "MAPPING_PENDING")
    proposal = json.loads(self.only_proposal_file().read_text())
    self.assertEqual(set(proposal), {"schema_version", "proposal_id", "input_file", "proposals"})
    self.assertEqual(set(proposal["proposals"][0]), {"column", "field", "score", "band", "reason", "decision", "use_field"})
def test_approvals(self):
    path = self.proposal_with_decisions({"NrCl": ("approve", ""), "C7": ("reject", ""), "Mob": ("change", "phone")})
    maps = apply_approval(path, ["NrCl", "C7", "Mob", "email"], self.dictionary_path)
    self.assertEqual((maps["NrCl"].source, maps["C7"].field, maps["Mob"].field), ("approved", None, "phone"))
    self.assertIn("nrcl", [match_key(n) for n in load_dictionary(self.dictionary_path)["card_number"]])
    with self.assertRaises(RunError) as e:
        apply_approval(self.proposal_with_decisions({"Mob": ("change", "fax")}), ["Mob"], self.dictionary_path)
    self.assertEqual(e.exception.code, "USAGE")
```

- [ ] **Step 2: Run the tests.** Expected: FAIL.
- [ ] **Step 3: Implement.** The simulated agent holds a fixed table of known abbreviations (for example `nrcl` → `card_number` 94, `mob` → `phone` 75) and otherwise scores by `difflib.SequenceMatcher` ratio between `match_key(column)` and each dictionary name × 100. Samples are the first 3 non-empty values of the column after control-character removal, masked unless their stripped lowercase form is in `STATUS_VALUES`. A field already mapped by another column is never proposed. Proposal file format exactly as the JSON example in spec 5, `schema_version` 1.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `simulated mapping agent, proposal file and approvals`.

### Task 10: Row processing [Essential]

**Files:** Create `ingest/rows.py`, `tests/test_rows.py`.

**Interfaces:**
- Consumes: `ReadResult`, `list[ColumnMap]`, every `fields.clean_*`, `parse_timestamp`, `timestamp_sort_key`.
- Produces: `process(read: ReadResult, maps: list[ColumnMap], run_time: datetime) -> Outcome`. Canonical rows hold the canonical fields in order, then pass-through columns by their header names. `missing_consent` / `missing_subscription` are derived from `maps`.

- [ ] **Step 1: Write the failing tests** (AC-11, AC-25, AC-27, AC-40 to AC-50, AC-53, Review Focus 4)

```python
def test_nine_combinations(self):
    out = self.run_rows([("1%015d" % i, c, s, "a@b.ro") for i, (c, s) in
                         enumerate(product(["da", "nu", "x"], ["activ", "inactiv", "x"]))])
    eligible = [r for r in out.canonical if r["eligible_for_campaign"] == "yes"]
    self.assertEqual(len(out.canonical), 9); self.assertEqual(len(eligible), 1)
    self.assertEqual(self.reasons(out, "1000000000000004"), "CONSENT_NOT_YES;SUBSCRIPTION_NOT_ACTIVE")
def test_no_contact(self):
    out = self.run_rows([("1111222233334444", "da", "activ", "")], app="nu")
    self.assertEqual(self.reasons(out, "1111222233334444"), "NO_CONTACT_CHANNEL")
    self.assertIn("NO_CONTACT_CHANNEL", [w.code for w in out.warnings])
def test_missing_consent_column(self):
    out = self.run_rows([("1111222233334444", None, "activ", "a@b.ro")], drop=["consent"])
    self.assertEqual(self.reasons(out, "1111222233334444"), "CONSENT_COLUMN_MISSING")
def test_newer_withdrawal_wins(self):
    out = self.run_rows_ts([("1111222233334444", "da", "2026-01-01"), ("1111222233334444", "nu", "2026-02-01")])
    self.assertEqual(out.canonical[0]["source_record_number"], "2")
    self.assertEqual(out.duplicates[0].reason, "LOST_OLDER_TIMESTAMP")
def test_tie_and_conflict(self):
    out = self.run_rows_ts([("1111222233334444", "da", "2026-01-01"), ("1111222233334444", "nu", "2026-01-01")])
    self.assertEqual(out.duplicates[0].reason, "LOST_TIE_LATER_ROW_WINS")
    self.assertIn("CONFLICTING_DUPLICATES", out.canonical[0]["ineligibility_reasons"])
    self.assertTrue({"DUPLICATE_TIE", "DUPLICATE_CONFLICT"} <= {w.code for w in out.warnings})
def test_invalid_timestamp_loses_without_conflict_when_states_agree(self):
    out = self.run_rows_ts([("1111222233334444", "da", "2026-01-01"), ("1111222233334444", "da", "2099-01-01")])
    self.assertEqual(out.duplicates[0].reason, "LOST_INVALID_TIMESTAMP")
    self.assertNotIn("CONFLICTING_DUPLICATES", out.canonical[0]["ineligibility_reasons"])
def test_three_rows_one_winner(self):
    out = self.run_rows_ts([("1111222233334444", "da", d) for d in ("2026-01-01", "2026-03-01", "2026-02-01")])
    self.assertEqual((len(out.canonical), len(out.duplicates)), (1, 2))
def test_card_spacing_is_one_key(self):
    out = self.run_rows_ts([("11112 222233334 44", "da", "2026-01-01"), ("1111222233334444", "da", "2026-02-01")])
    self.assertEqual(len(out.duplicates), 1)
def test_totals_and_all_cards_empty(self):
    out = self.run_rows([("", "da", "activ", "a@b.ro")] * 3)
    self.assertEqual((len(out.canonical), len(out.rejected)), (0, 3))
    self.assertEqual(out.rejected[0].codes, ["CARD_EMPTY"])
```

The helpers build a `ReadResult` directly, so this task does not depend on reading files.

- [ ] **Step 2: Run `python -m unittest tests.test_rows -v`.** Expected: FAIL.
- [ ] **Step 3: Implement `process`** following spec 7.1 to 7.3. Ineligibility reasons in this fixed order: `CONSENT_NOT_YES` or `CONSENT_COLUMN_MISSING`, `SUBSCRIPTION_NOT_ACTIVE` or `SUBSCRIPTION_COLUMN_MISSING`, `NO_CONTACT_CHANNEL`, `CONFLICTING_DUPLICATES`. Duplicate winner key: `(has_valid_timestamp, timestamp_sort_key, record_number)`, maximum wins. A rejected record keeps every reason that applies (card reason plus any read reason). Field warnings carry the record number and the field name.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `row processing, duplicates and eligibility`.

### Task 11: Writing, verifying and publishing [Essential]

**Files:** Create `ingest/writer.py`, `ingest/publish.py`, `tests/test_outputs.py`.

**Interfaces:**
- Consumes: `Outcome`, `list[ColumnMap]`, `codes.MESSAGES`.
- Produces: `write_outputs(temp: Path, outcome: Outcome, maps, summary: dict) -> None`, which calls `write_canonical`, `write_rejected`, `write_warnings`, `write_duplicates` and `write_summary` (each `(temp: Path, ...) -> None`); `build_summary(...) -> dict` with exactly the keys of the spec 8 example; `verify(temp: Path, rows_received: int) -> None` raising `VERIFY_FAILED` (re-reads every CSV, recounts rows, checks the equation); `publish(temp: Path, run_folder: Path) -> None` raising `RUN_FOLDER_EXISTS`; `discard(temp: Path, debug: bool, failed_name: str) -> None`.

- [ ] **Step 1: Write the failing tests** (AC-54 to AC-58, AC-60, AC-62, AC-63)

```python
def test_five_files_with_headers_when_empty(self):
    self.write_and_publish(self.clean_outcome())
    self.assertEqual(sorted(p.name for p in self.run_folder.iterdir()),
                     ["canonical_customers.csv", "duplicates.csv", "rejected_rows.csv",
                      "run_summary.json", "warnings.csv"])
    self.assertEqual(self.lines("duplicates.csv"), ["card_number,source_record_number,last_interaction_at,kept_record_number,reason"])
def test_rejected_rows_one_line_each(self):
    self.write_and_publish(self.outcome_with_rejected([["CARD_EMPTY"], ["CARD_INVALID", "EXTRA_CELLS"]]))
    rows = self.csv_rows("rejected_rows.csv")
    self.assertEqual([r["reason_codes"] for r in rows], ["CARD_EMPTY", "CARD_INVALID;EXTRA_CELLS"])
    self.assertEqual(len({len(r) for r in rows}), 1)
def test_utf8_without_bom(self):
    self.write_and_publish(self.outcome_with_name("Ștefan Țurcanu"))
    raw = (self.run_folder / "canonical_customers.csv").read_bytes()
    self.assertFalse(raw.startswith(b"\xef\xbb\xbf")); self.assertIn("Ștefan Țurcanu", raw.decode("utf-8"))
def test_summary_contract(self):
    s = self.write_and_publish(self.clean_outcome())
    self.assertEqual(s["schema_version"], 1); self.assertIn("export_date", s)
    self.assertEqual(set(s["stages"]), {"read", "clean", "write", "verify"})
    self.assertNotIn("schema_version", self.csv_rows("canonical_customers.csv")[0])
def test_verify_failure_publishes_nothing(self):
    self.write_outputs_only(self.clean_outcome())
    (self.temp / "warnings.csv").write_text("broken")
    with self.assertRaises(RunError) as e: verify(self.temp, rows_received=1)
    self.assertEqual(e.exception.code, "VERIFY_FAILED")
def test_existing_run_folder_untouched(self):
    self.run_folder.mkdir(); (self.run_folder / "keep.txt").write_text("x")
    with self.assertRaises(RunError) as e: publish(self.temp, self.run_folder)
    self.assertEqual(e.exception.code, "RUN_FOLDER_EXISTS"); self.assertTrue((self.run_folder / "keep.txt").exists())
def test_discard(self):
    discard(self.temp, debug=False, failed_name="failed_2026-11-05_083300Z"); self.assertFalse(self.temp.exists())
```

- [ ] **Step 2: Run `python -m unittest tests.test_outputs -v`.** Expected: FAIL.
- [ ] **Step 3: Implement.** CSV via `csv.writer(f, lineterminator="\n")` with `encoding="utf-8"`, `newline=""`. Temporary folder: `<output>/.tmp_<run_id>`. Publishing is `os.rename` after checking that the target does not exist. `export_date` = modification date of the input file in local time, ISO date. Percentages carry the `_pct` suffix.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `output writing, verification and publishing`.

### Task 12: Time and memory measurement [Essential]

**Files:** Create `ingest/ops.py`, `tests/test_ops.py`.

**Interfaces:**
- Produces: `StageTimer` (context manager per stage; `results() -> dict[str, dict[str, float]]` with `duration_ms` and `peak_memory_mb`; `total_ms()`), all on `time.monotonic()`; `peak_memory_mb() -> float | None`; `total_memory_mb() -> float | None`; `setup_log(log_path: Path) -> logging.Logger` writing `UTC-time LEVEL stage CODE message` to stderr and the file.

- [ ] **Step 1: Write the failing tests** (AC-57, AC-67 for the log format)

```python
def test_stage_timer(self):
    t = StageTimer()
    for stage in ("read", "clean", "write", "verify"):
        with t.stage(stage): pass
    self.assertEqual(list(t.results()), ["read", "clean", "write", "verify"])
    self.assertGreaterEqual(t.total_ms(), sum(v["duration_ms"] for v in t.results().values()))
def test_memory_readings(self):
    self.assertGreater(peak_memory_mb(), 0)
    total = total_memory_mb()
    self.assertTrue(total is None or total > peak_memory_mb())
@unittest.skipUnless(sys.platform == "win32", "Windows only")
def test_windows_memory(self):
    self.assertGreater(total_memory_mb(), 0); self.assertGreater(peak_memory_mb(), 0)
```

- [ ] **Step 2: Run `python -m unittest tests.test_ops -v`.** Expected: FAIL.
- [ ] **Step 3: Implement Linux and Windows readers.** Linux: `resource.getrusage(RUSAGE_SELF).ru_maxrss` in KiB; total from `MemTotal` in `/proc/meminfo`. Windows: `ctypes` with `GetProcessMemoryInfo` (`PROCESS_MEMORY_COUNTERS.PeakWorkingSetSize`) from `psapi`/`kernel32`, and `GlobalMemoryStatusEx` (`MEMORYSTATUSEX.ullTotalPhys`). Any exception → `None`.
- [ ] **Step 4 [Important]: Add macOS.** `ru_maxrss` in bytes; total from `subprocess.run(["sysctl", "-n", "hw.memsize"])`.
- [ ] **Step 5: Run the tests.** Expected: PASS here; the Windows test is run on the Windows laptop before delivery (spec 10.3 step 6).
- [ ] **Step 6: Commit** `stage timing, memory readings and log format`.

### Task 13: Command line and run orchestration [Essential]

**Files:** Create `ingest/cli.py`, `tests/test_cli.py`; modify `ingest/__main__.py`.

**Interfaces:**
- Consumes: everything above.
- Produces: `main(argv: list[str] | None = None) -> int`. Order: parse arguments (`USAGE` before any file is touched) → `read_file` → mapping (dictionary, agent, `--approve`) → `process` → write into the temporary folder → `verify` → `publish`. Every `RunError` prints the operator line and returns its exit code; any other exception becomes `INTERNAL_ERROR` naming the current stage; the temporary folder is discarded on every failure.

- [ ] **Step 1: Write the failing tests** (AC-01, AC-02, AC-22 usage, AC-59, AC-60, AC-61, AC-63, AC-64, AC-67, Review Focus 2 and 3)

```python
def test_success_exit_0_and_run_folder_in_utc(self):
    code, out, err = self.cli(["run", "--input", str(self.fixture("small.csv")), "--output", str(self.out)])
    self.assertEqual(code, 0)
    self.assertRegex(self.only_run_folder().name, r"^run_\d{4}-\d{2}-\d{2}_\d{6}Z$")
def test_usage(self):
    self.assertEqual(self.cli(["run"])[0], 2)
    self.assertEqual(self.cli(["run", "--input", "x.csv", "--memory-stop", "120"])[0], 2)
def test_input_is_a_folder(self):
    code, _, err = self.cli(["run", "--input", str(self.out), "--output", str(self.out)])
    self.assertEqual(code, 2); self.assertIn("ERROR INPUT_UNREADABLE", err)
def test_output_is_a_file(self):
    f = self.tmp / "file"; f.write_text("x")
    code, _, err = self.cli(["run", "--input", str(self.fixture("small.csv")), "--output", str(f)])
    self.assertEqual(code, 2); self.assertIn("ERROR OUTPUT_NOT_WRITABLE", err)
def test_internal_error_has_no_traceback(self):
    with mock.patch("ingest.rows.process", side_effect=ZeroDivisionError):
        code, _, err = self.cli(self.small_args())
    self.assertEqual(code, 5); self.assertIn("ERROR INTERNAL_ERROR [stage clean]", err)
    self.assertNotIn("Traceback", err); self.assertEqual(self.run_folders(), [])
def test_failure_after_some_files_written(self):
    with mock.patch("ingest.writer.write_duplicates", side_effect=OSError("disk full")):
        code, _, err = self.cli(self.small_args())
    self.assertNotEqual(code, 0); self.assertEqual(self.run_folders(), []); self.assertEqual(self.temp_folders(), [])
def test_same_input_twice_same_files(self):
    self.cli(self.small_args()); first = self.only_run_folder()
    time.sleep(1.1); self.cli(self.small_args()); second = [f for f in self.run_folders() if f != first][0]
    for name in ("canonical_customers.csv", "rejected_rows.csv", "warnings.csv", "duplicates.csv"):
        self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
def test_log_has_no_personal_values(self):
    self.cli(self.small_args())
    log = self.only_log().read_text()
    for value in ("1111222233334444", "ana@example.com", "+40722123456", "Gheorghe"):
        self.assertNotIn(value, log)
```

`small.csv` is a fixture with one valid customer, one duplicate, one rejected row and one warning; its expected counts are worked out by hand in the test docstring.

- [ ] **Step 2: Run `python -m unittest tests.test_cli -v`.** Expected: FAIL.
- [ ] **Step 3: Implement `main`.** Call each stage through its module (`rows.process`, `writer.write_outputs`) so that tests can patch it. Use `argparse` (subcommand `run`; arguments, defaults and ranges from spec 3). Run id from `datetime.now(timezone.utc)`; `run_started_at` with the local offset. Exit 3 path: the proposal file path is printed and nothing else is written.
- [ ] **Step 4: Run all tests: `python -m unittest -v`.** Expected: PASS.
- [ ] **Step 5: Commit** `command line, run orchestration and operator messages`.

### Task 14: Synthetic data and volume [Essential]

**Files:** Create `tools/generate_synthetic.py`, `tests/test_volume.py`.

**Interfaces:**
- Produces: `python tools/generate_synthetic.py --rows N --out <file.csv> --seed 42`, a deterministic file with a fixed share of each problem (about 0.3% rejected rows, 0.6% duplicates, some warnings of each kind, no personal data from real people).

- [ ] **Step 1: Write the failing test** (AC-68)

```python
@unittest.skipUnless(os.environ.get("INGEST_VOLUME") == "1", "set INGEST_VOLUME=1 to run")
class VolumeTest(unittest.TestCase):
    def test_100k(self):
        generate(rows=100_000, out=self.csv, seed=42)
        self.assertEqual(main(["run", "--input", str(self.csv), "--output", str(self.out)]), 0)
        s = self.summary()
        self.assertTrue(s["destinations"]["reconciled"])
        self.assertEqual(s["input"]["rows_received"], 100_000)
        for stage in ("read", "clean", "write", "verify"):
            self.assertGreater(s["stages"][stage]["duration_ms"], 0)
```

- [ ] **Step 2: Run `INGEST_VOLUME=1 python -m unittest tests.test_volume -v`.** Expected: FAIL.
- [ ] **Step 3: Implement the generator.** Names from a small fixed list of invented first and last names; cards from the seeded random generator; dates spread over the past two years.
- [ ] **Step 4: Run the volume test.** Expected: PASS; note duration and peak memory.
- [ ] **Step 5: Measure 10x.** Generate 1,000,000 rows, run once, copy the stage durations and peak memory from `run_summary.json` into a table for the README.
- [ ] **Step 6: Attempt 100x.** Generate 10,000,000 rows and run with the default thresholds. Record either the figures or the clean `MEMORY_LIMIT` stop (exit 4) once Task 15 exists; without Task 15, record the peak memory reached and the outcome as observed.
- [ ] **Step 7: Commit** `synthetic data generator and volume test` (generated files are not committed).

### Task 15: Run thresholds [Important]

**Files:** Modify `ingest/rows.py`, `ingest/cli.py`, `ingest/ops.py`; tests in `tests/test_rows.py`, `tests/test_ops.py`.

**Interfaces:** Produces `run_flags(outcome, rows_received, thresholds) -> tuple[list[Warning], dict]` (warnings `MISSING_CONTACT_THRESHOLD`, `REJECTION_RATE_HIGH`, and the `observed` and `flags` parts of the summary); `MemoryGuard(warn_pct, stop_pct, total_mb).check(stage)` raising `MEMORY_LIMIT` and emitting `MEMORY_WARNING` once, or `MEMORY_TOTAL_UNKNOWN` when the total is `None`; called at the end of each stage and every 10,000 records in read and clean.

- [ ] **Step 1: Write the failing tests** (AC-51, AC-52, AC-65)

```python
def test_missing_contact_threshold(self):
    warnings, summary = run_flags(self.outcome(canonical=100, without_contact=4), 100, DEFAULTS)
    self.assertIn("MISSING_CONTACT_THRESHOLD", [w.code for w in warnings])
    warnings, _ = run_flags(self.outcome(canonical=100, without_contact=3), 100, DEFAULTS)
    self.assertNotIn("MISSING_CONTACT_THRESHOLD", [w.code for w in warnings])
def test_rejection_rate(self):
    warnings, _ = run_flags(self.outcome(canonical=89, rejected=11), 100, DEFAULTS)
    self.assertIn("REJECTION_RATE_HIGH", [w.code for w in warnings])
def test_memory_guard(self):
    guard = MemoryGuard(50, 80, total_mb=1000)
    with mock.patch("ingest.ops.peak_memory_mb", return_value=600): self.assertEqual(guard.check("read"), ["MEMORY_WARNING"])
    with mock.patch("ingest.ops.peak_memory_mb", return_value=601): self.assertEqual(guard.check("read"), [])
    with mock.patch("ingest.ops.peak_memory_mb", return_value=801), self.assertRaises(RunError) as e: guard.check("clean")
    self.assertEqual(e.exception.code, "MEMORY_LIMIT")
    self.assertEqual(MemoryGuard(50, 80, total_mb=None).check("read"), ["MEMORY_TOTAL_UNKNOWN"])
```

- [ ] **Step 2: Run the tests.** Expected: FAIL.
- [ ] **Step 3: Implement** and wire into `main`; exit code 4 for `MEMORY_LIMIT`.
- [ ] **Step 4: Run all tests.** Expected: PASS.
- [ ] **Step 5: Commit** `missing-contact, rejection and memory thresholds`.

### Task 16: Repeated and skipped local hour [Important]

**Files:** Modify `ingest/fields.py`, `tests/test_fields.py`.

**Interfaces:** `parse_timestamp(raw, run_time, tz=None)` gains an optional `tz` (a `zoneinfo.ZoneInfo`, default the machine's local zone) so the test is independent of the machine.

- [ ] **Step 1: Write the failing test** (AC-36)

```python
def test_ambiguous_and_skipped_hour(self):
    tz = ZoneInfo("Europe/Bucharest")
    run = datetime(2026, 11, 5, tzinfo=tz)
    self.assertEqual(parse_timestamp("2026-10-25 03:30", run, tz).codes, ["TIMESTAMP_AMBIGUOUS_HOUR"])
    self.assertEqual(parse_timestamp("2026-03-29 03:30", run, tz).codes, ["TIMESTAMP_AMBIGUOUS_HOUR"])
    self.assertEqual(parse_timestamp("2026-10-25 05:30", run, tz).codes, [])
```

- [ ] **Step 2: Run the test.** Expected: FAIL.
- [ ] **Step 3: Implement.** Repeated hour: `fold=0` and `fold=1` give different UTC offsets. Skipped hour: converting to UTC and back does not return the same wall time. `zoneinfo` needs the `tzdata` package on Windows; when the zone cannot be loaded, fall back to the fixed local offset from `datetime.now().astimezone()` and skip this check (no warning, no crash).
- [ ] **Step 4: Run all tests.** Expected: PASS.
- [ ] **Step 5: Commit** `warning for repeated and skipped local hours`.

### Task 17: Permissions, debug folder, agent fallback [Important]

**Files:** Modify `ingest/publish.py`, `ingest/mapping.py`, `ingest/cli.py`; tests in `tests/test_outputs.py`, `tests/test_mapping.py`, `tests/test_cli.py`.

**Interfaces:** `restrict_permissions(folder: Path) -> list[Warning]` (folder `0o700`, files `0o600` on POSIX; `PERMISSIONS_SKIPPED` elsewhere); `discard(..., debug=True)` renames the temporary folder to `failed_YYYY-MM-DD_HHMMSSZ`; an exception from the agent gives `MAPPING_AGENT_FALLBACK` and dictionary-only mapping.

- [ ] **Step 1: Write the failing tests** (AC-23, AC-63 debug, AC-66)

```python
@unittest.skipIf(os.name != "posix", "POSIX only")
def test_owner_only(self):
    self.write_and_publish(self.clean_outcome())
    self.assertEqual(stat.S_IMODE(self.run_folder.stat().st_mode), 0o700)
    self.assertEqual(stat.S_IMODE((self.run_folder / "warnings.csv").stat().st_mode), 0o600)
def test_debug_keeps_failed_folder(self):
    discard(self.temp, debug=True, failed_name="failed_2026-11-05_083300Z")
    self.assertTrue((self.out / "failed_2026-11-05_083300Z").is_dir())
def test_agent_failure_falls_back(self):
    maps, proposals, warnings = map_header_with_samples(["NrCl", "card"], [], self.dictionary, BrokenAgent())
    self.assertEqual((proposals, warnings[0].code), ([], "MAPPING_AGENT_FALLBACK"))
```

- [ ] **Step 2: Run the tests.** Expected: FAIL.
- [ ] **Step 3: Implement** and wire `--debug` into `main`.
- [ ] **Step 4: Run all tests.** Expected: PASS.
- [ ] **Step 5: Commit** `restrictive permissions, debug failed folder, agent fallback`.

### Task 18: Documentation and delivery check [Essential]

**Files:** Create `README.md`, `CLAUDE.md`, `AGENTS.md`; update `docs/ai-log.md`; keep `docs/brainstorming/brainstorming.md`, `docs/specification/specification.md`, this plan.

- [ ] **Step 1: Write `README.md`.** Sections: purpose and customer context (assumed); setup (Python 3.11+, nothing to install); how to run on Windows (`py -m ingest run --input ...`) and on macOS and Linux (`python3 -m ingest run --input ...`); outputs; exit codes; how to approve a mapping; architecture (stages and modules); assumptions and decisions (pointer to the brainstorming); known limitation (stray quote inside an unquoted field); performance table with the 1x, 10x and 100x figures from Task 14, labelled measured or estimated; what was not implemented (any Important task not done, the Optional list); AI use (what was delegated, what was rejected, how it was checked; pointer to `docs/ai-log.md`).
- [ ] **Step 2: Write `CLAUDE.md` and `AGENTS.md`.** Same content: how to run the tests, where the spec and plan are, the rule that every code comes from spec section 9, that documents are impersonal and in English, and that test expectations come from the spec.
- [ ] **Step 3: Update `docs/ai-log.md`** with the plan and implementation rows (what the AI proposed, what was rejected or changed, how it was verified).
- [ ] **Step 4: Verify from a clean checkout.** Run: `git clone <repo> /tmp/check && cd /tmp/check && python -m unittest -v && python -m ingest run --input tests/fixtures/small.csv --output /tmp/check/runs`. Expected: all tests pass, exit 0, one run folder. Check that every file named in the README exists and that `.gitignore` covers `runs/`.
- [ ] **Step 5: Run the Windows checks on the laptop.** `py -m unittest -v` (the Windows memory test runs there) and one real run; note the Python version in the README.
- [ ] **Step 6: Commit** `README, agent instructions and AI log`.

### Task 19: OpenSpec version of the specification [Important]

**Files:** Create `openspec/` (by `openspec init`), `openspec/specs/ingestion/spec.md`; modify `README.md`, `CLAUDE.md`, `AGENTS.md`.

- [ ] **Step 1: Initialize.** Run `openspec init --tools claude` in the repository root. Expected: an `openspec/` folder and no change to existing files other than the ones OpenSpec documents in its output; review the diff before keeping it.
- [ ] **Step 2: Write `openspec/specs/ingestion/spec.md`.** One `### Requirement:` per subsection of spec sections 4 to 10, each with `SHALL` wording taken from the spec, and one `#### Scenario:` per acceptance case in WHEN/THEN form, titled with its AC number. No rule that is not in `docs/specification/specification.md`.
- [ ] **Step 3: Validate.** Run `openspec validate --specs` (or the validation command the installed version lists in `openspec --help`). Expected: no errors.
- [ ] **Step 4: Point to it.** README, `CLAUDE.md` and `AGENTS.md` say that `docs/specification/specification.md` is the source and `openspec/specs/ingestion/spec.md` mirrors it, and that a future change starts as an OpenSpec change proposal.
- [ ] **Step 5: Commit** `Task 19: OpenSpec version of the specification`.

