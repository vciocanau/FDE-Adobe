# ingestion Specification

## Purpose

Ingest one CRM customer-profile CSV export of a supermarket chain with a loyalty card into a canonical customer table with export-time campaign eligibility, together with rejected rows, losing duplicates, warnings and a run summary. This file mirrors `docs/specification/specification.md`, which is the source; each scenario carries the number of its acceptance case.

## Requirements

### Requirement: Input file checks
The system SHALL stop with a named run error, and publish nothing, when the input file is missing, unreadable, empty, not valid UTF-8 or has a header and no records; a BOM SHALL be ignored.

#### Scenario: AC-01
- **WHEN** Input path does not exist
- **THEN** `INPUT_NOT_FOUND` naming the path, exit 2, no result files, no traceback

#### Scenario: AC-02
- **WHEN** Input file exists but cannot be read (no permission)
- **THEN** `INPUT_UNREADABLE` naming the file and the reason, exit 2, no result files

#### Scenario: AC-03
- **WHEN** Empty file (zero bytes)
- **THEN** `INPUT_EMPTY`, exit 1, no result files

#### Scenario: AC-04
- **WHEN** Header only, and a header followed only by blank rows
- **THEN** `NO_DATA_ROWS`, exit 1, no result files

#### Scenario: AC-07
- **WHEN** Invalid UTF-8 in the header, and invalid UTF-8 in a record further down
- **THEN** `INVALID_UTF8`, exit 1, nothing replaced, no result files

#### Scenario: AC-08
- **WHEN** File that starts with a BOM
- **THEN** Read normally; the first column name has no hidden character

### Requirement: Delimiter and header
The system SHALL accept comma and semicolon delimiters detected from the header line, and SHALL stop when the first line does not look like a header or another delimiter is used.

#### Scenario: AC-05
- **WHEN** First line holds a card number instead of column names
- **THEN** `NO_HEADER`, exit 1, no result files

#### Scenario: AC-06
- **WHEN** A file with semicolons, and a file with tabs
- **THEN** The semicolon file gives the same result as the comma file; the tab file stops with `UNSUPPORTED_DELIMITER`, exit 1, naming the accepted delimiters

### Requirement: Strict record reading
The system SHALL read records strictly: a record with a value in an extra cell or text after a closing quote SHALL be rejected alone, an unclosed quote or a record spanning more than 5 physical lines SHALL stop the run, and no value SHALL move silently to another column.

#### Scenario: AC-09
- **WHEN** The same file with LF, CRLF and CR line endings
- **THEN** Identical results

#### Scenario: AC-10
- **WHEN** A row with extra cells that are all empty, and a row with a value in an extra cell
- **THEN** The first is kept with `TRAILING_EMPTY_CELLS`; the second is rejected with `EXTRA_CELLS`, kept in full with its `source_record_number`; the run continues; totals reconcile

#### Scenario: AC-11
- **WHEN** A row with fewer cells than the header
- **THEN** Kept, missing cells empty, `SHORT_ROW`; a missing card rejects the row (`CARD_EMPTY`); a missing consent or subscription is `unknown`; totals reconcile

#### Scenario: AC-12
- **WHEN** Optional and pass-through cells empty in some rows, filled in others
- **THEN** Filled values kept, empty cells stay empty, no row rejected for that

#### Scenario: AC-13
- **WHEN** Text right after a closing quote (`"abc"def`)
- **THEN** That row alone is rejected with `BAD_QUOTING`; the run continues

#### Scenario: AC-14
- **WHEN** A quoted field that closes correctly after 2 to 5 physical lines
- **THEN** Row kept with `MULTILINE_RECORD`

#### Scenario: AC-15
- **WHEN** A quote that is never closed
- **THEN** `UNCLOSED_QUOTE` naming the line where the record started, exit 1, nothing published

#### Scenario: AC-16
- **WHEN** A quote closed by accident further down, merging rows over 15 lines
- **THEN** `UNCLOSED_QUOTE` naming the line where the record started, exit 1, nothing published

#### Scenario: AC-17
- **WHEN** A quote in the middle of an unquoted field (`ab"c`)
- **THEN** Read as text without an error (the documented known limitation)

### Requirement: Header mapping
The system SHALL map columns by the synonym dictionary, SHALL stop with a proposal file when the simulated agent proposes a field with a score of 60 or more, SHALL never approve a mapping by itself, and SHALL show the agent only column names and up to 3 masked samples.

#### Scenario: AC-18
- **WHEN** No column maps to the card
- **THEN** `CARD_COLUMN_MISSING`, exit 1, no result files

#### Scenario: AC-19
- **WHEN** Two columns map to the same field
- **THEN** `FIELD_MAPPED_TWICE`, exit 1, nothing guessed

#### Scenario: AC-20
- **WHEN** A column with an unknown name and no proposal (score below 60)
- **THEN** Passed through after the fixed columns, `UNKNOWN_COLUMN`; the run continues

#### Scenario: AC-21
- **WHEN** A new column with a proposal scoring above 90, and one scoring 60 to 90
- **THEN** The run stops with `MAPPING_PENDING`, exit 3, and writes a proposal file showing the band; nothing is approved automatically; columns below 60 are listed with an empty field

#### Scenario: AC-22
- **WHEN** Rerun with `--approve` after decisions approve, reject, change to a known field, change to an unknown field
- **THEN** Approved and changed mappings are used and saved in the dictionary; a rejected mapping is passed through with `UNKNOWN_COLUMN`; a change to an unknown field is a `USAGE` error, exit 2

#### Scenario: AC-23
- **WHEN** The simulated agent fails
- **THEN** The run falls back to the dictionary with `MAPPING_AGENT_FALLBACK` and does not stop

#### Scenario: AC-24
- **WHEN** What the agent receives
- **THEN** Column names and at most 3 masked samples per column: letters become `x`, digits become `9`; status values such as `da`, `nu`, `yes`, `active` stay unmasked; no complete row, no unmasked card, email or phone

### Requirement: Control characters
The system SHALL remove Unicode control characters other than TAB, LF and CR from every value and header name before any field rule, and SHALL write the warning CONTROL_CHARACTER_REMOVED naming the field.

#### Scenario: AC-25
- **WHEN** A control character in a name, card, email, phone, consent, subscription, app installed and pass-through value
- **THEN** The character is removed, the rest follows the field's rule, `CONTROL_CHARACTER_REMOVED` names the field; written files stay valid

#### Scenario: AC-26
- **WHEN** Name `Gheorghe` followed by U+0001
- **THEN** Stored as `Gheorghe` with `CONTROL_CHARACTER_REMOVED`; the row is kept

#### Scenario: AC-28
- **WHEN** A 16-digit card with a control character inside, and a 15-digit card with one
- **THEN** The first is valid with `CONTROL_CHARACTER_REMOVED`; the second is rejected with `CARD_INVALID`

### Requirement: Loyalty card
The system SHALL accept a card only as exactly 16 ASCII digits after removing whitespace and dashes, and SHALL reject any other value.

#### Scenario: AC-27
- **WHEN** Cards `1234 5678`, `12345678901234AB`, empty, `1.23457E+15`
- **THEN** Rejected: `CARD_INVALID`, `CARD_INVALID`, `CARD_EMPTY`, `CARD_INVALID`; not in the canonical table; totals reconcile

### Requirement: Names
The system SHALL trim names, collapse inner whitespace, normalize to NFC and convert cedilla ş ţ to comma-below ș ț, keeping letter case and other diacritics.

#### Scenario: AC-29
- **WHEN** Names with cedilla ş ţ and with comma-below ș ț
- **THEN** Both give the identical value

#### Scenario: AC-30
- **WHEN** A name with extra inner spaces and a decomposed accent
- **THEN** Trimmed, inner spaces collapsed, stored in NFC

#### Scenario: AC-31
- **WHEN** First name or last name absent or empty
- **THEN** Profile kept with empty names; no rejection

### Requirement: Phone
The system SHALL normalize Romanian phone numbers to +40, SHALL treat a nine-digit number starting with 7 as a mobile number with a lost leading 0, and SHALL empty numbers with fewer than 8 or more than 15 digits.

#### Scenario: AC-32
- **WHEN** Phones `0722123456`, `722123456`, `0040722123456`, `+40722123456`, `12345`
- **THEN** The first four give `+40722123456`; `722123456` adds `PHONE_LEADING_ZERO`; `12345` is emptied with `PHONE_INVALID`

### Requirement: Email
The system SHALL trim and lowercase emails and SHALL empty an email with a space, a number of @ other than one, or no dot after the @.

#### Scenario: AC-33
- **WHEN** Emails `Ana@Example.COM` (with surrounding spaces), `ana @example.com`, `ana@@example.com`, `ana@example`
- **THEN** The first gives `ana@example.com`; the others are emptied with `EMAIL_INVALID`

### Requirement: Dates
The system SHALL read dates day first in ISO 8601, DD.MM.YYYY and DD/MM/YYYY with an optional time, SHALL store them in ISO 8601, and SHALL empty unreadable, out-of-range and future values with a warning.

#### Scenario: AC-34
- **WHEN** Dates `2026-11-04`, `04.11.2026`, `04/11/2026`, `2026-11-04 14:30`, `11/13/2026`, `13.13.2026`, `31.02.2026`
- **THEN** The first three give the same value; the fourth is kept with its time; the last three are emptied with `TIMESTAMP_UNREADABLE`; the profile is kept

#### Scenario: AC-35
- **WHEN** Timestamps `0001-01-01T00:00:00+01:00` and one later than the run time
- **THEN** Emptied with `TIMESTAMP_OUT_OF_RANGE` and `TIMESTAMP_IN_FUTURE`; the profile is kept; no crash

#### Scenario: AC-36
- **WHEN** A timestamp without a zone in the hour that repeats when daylight saving time ends
- **THEN** Kept, read in local time, `TIMESTAMP_AMBIGUOUS_HOUR`

### Requirement: Status values
The system SHALL normalize consent to yes, no or unknown, subscription to active, inactive or unknown, and app installed to yes, no or unknown, using separate lists, and SHALL treat anything else as unknown with a warning.

#### Scenario: AC-37
- **WHEN** Every consent value in the lists, in mixed case and spacing; empty; `nu accept`
- **THEN** Listed values give `yes` or `no`; empty and `nu accept` give `unknown` with `CONSENT_UNKNOWN`

#### Scenario: AC-38
- **WHEN** Every subscription value in the lists, in mixed case and with surrounding spaces; empty; unrecognized
- **THEN** Listed values give `active` or `inactive`; the others give `unknown` with `SUBSCRIPTION_UNKNOWN`

### Requirement: Last purchase amount
The system SHALL accept a positive amount with an optional decimal part of 1 or 2 digits after a dot or a comma, and SHALL empty zero, negative, currency-marked and thousands-separated values with a warning.

#### Scenario: AC-39
- **WHEN** Amounts `12.50`, `12,50`, `-12.50`, `0`, `12 lei`, `1,234`, `abc`
- **THEN** `12.50` and `12,50` give `12.50`; the others are emptied with `PURCHASE_AMOUNT_INVALID`; the profile is kept

### Requirement: Eligibility
A canonical customer SHALL be eligible for campaigns only with consent yes, subscription active and at least one valid contact channel, and every reason for ineligibility SHALL be listed.

#### Scenario: AC-40
- **WHEN** The nine combinations of consent `yes`/`no`/`unknown` and subscription `active`/`inactive`/`unknown`, each with a valid card and email
- **THEN** Only `yes` + `active` is eligible; all nine stay canonical with every reason in `ineligibility_reasons`; unknown states give warnings

#### Scenario: AC-41
- **WHEN** Consent `yes`, subscription `active`, no valid email, phone or app
- **THEN** Canonical, not eligible, `NO_CONTACT_CHANNEL` as reason and warning; counted for the 3% threshold

#### Scenario: AC-42
- **WHEN** No consent column, and no subscription column
- **THEN** Every customer not eligible with `CONSENT_COLUMN_MISSING` or `SUBSCRIPTION_COLUMN_MISSING`, and the run warning; all five outputs published

### Requirement: Duplicates
Among rows sharing a card, the row with the most recent valid interaction timestamp SHALL win, consent and subscription SHALL come only from the winner, and a customer whose duplicates disagree when the order cannot be known SHALL NOT be eligible.

#### Scenario: AC-43
- **WHEN** Same card twice: the older row eligible, the newer row with consent `no` or subscription `inactive`
- **THEN** The newer row wins; not eligible; the older row in `duplicates.csv` with `LOST_OLDER_TIMESTAMP`

#### Scenario: AC-44
- **WHEN** Same card twice with the same timestamp, and with both timestamps missing
- **THEN** The later record wins with `DUPLICATE_TIE`; the other has `LOST_TIE_LATER_ROW_WINS`

#### Scenario: AC-45
- **WHEN** The same card written with spaces in groups of 5, 9 and 2 digits, and without spaces
- **THEN** Same key; the second is handled as a duplicate

#### Scenario: AC-46
- **WHEN** Same card twice, same states, older row with a real timestamp, newer row in the future
- **THEN** The future timestamp is emptied with `TIMESTAMP_IN_FUTURE`; the real one wins; the other has `LOST_INVALID_TIMESTAMP`

#### Scenario: AC-47
- **WHEN** Same card twice, one timestamp missing, rows disagree on consent
- **THEN** Not eligible with `CONFLICTING_DUPLICATES` and `DUPLICATE_CONFLICT`

#### Scenario: AC-48
- **WHEN** Same card twice, same timestamp, rows disagree on subscription
- **THEN** The later record wins; not eligible with `CONFLICTING_DUPLICATES` and `DUPLICATE_CONFLICT`

#### Scenario: AC-49
- **WHEN** Same card twice, one timestamp missing, rows agree on both states
- **THEN** The row with the valid timestamp wins; no conflict reason

#### Scenario: AC-50
- **WHEN** Same card three times
- **THEN** One winner; the other two in `duplicates.csv`, each compared with the winner

### Requirement: Totals and thresholds
Rows received SHALL equal canonical plus rejected plus losing duplicates, and the run SHALL warn above the missing-contact and rejection thresholds without stopping.

#### Scenario: AC-51
- **WHEN** More than 3% of canonical customers without a contact channel, and a file with exactly 3%
- **THEN** Above: `MISSING_CONTACT_THRESHOLD`; at 3%: only the row warnings; both counts in the summary

#### Scenario: AC-52
- **WHEN** More than 10% of rows rejected
- **THEN** `REJECTION_RATE_HIGH`; the run is not stopped

#### Scenario: AC-53
- **WHEN** One canonical winner, one losing duplicate, one rejected row
- **THEN** received = canonical + rejected + duplicate losing; warnings are not counted as rows

### Requirement: Output contract
A successful run SHALL publish exactly five files in a new UTC-named run folder, written in UTF-8 without a BOM, with the schema version and export date in the run summary only.

#### Scenario: AC-54
- **WHEN** A clean file with no rejections, warnings or duplicates
- **THEN** All five files exist; empty CSV files keep their headers; the summary reconciles counts and records the thresholds

#### Scenario: AC-55
- **WHEN** A rejected row with one error and one with several
- **THEN** One line each, same columns, all errors in one column

#### Scenario: AC-56
- **WHEN** Output contract of a successful run
- **THEN** The summary holds `schema_version` and `export_date` (modification date of the input file); the canonical table has no schema version column; eligibility is labelled as at export time; no message is sent

#### Scenario: AC-57
- **WHEN** Summary of a successful run
- **THEN** Duration and peak memory of each of the four stages, total duration, and the `mapping` list with a source for every input column

#### Scenario: AC-58
- **WHEN** Names with ș and ț written to the CSV files
- **THEN** UTF-8 without a BOM; the names read back identical

#### Scenario: AC-59
- **WHEN** Two runs one after the other, also one hour apart across the daylight saving change
- **THEN** Each has its own folder named in UTC ending in `Z`; the first folder is untouched

#### Scenario: AC-60
- **WHEN** The same input run twice
- **THEN** The same files with the same content, apart from run times and durations in the summary

### Requirement: Failures and operations
A failed run SHALL publish nothing and SHALL print one operator line without a traceback; the log SHALL hold no personal value; memory SHALL be checked against the warning and stop thresholds; run files SHALL be readable only by their owner where the system allows it.

#### Scenario: AC-61
- **WHEN** Output folder not writable
- **THEN** `OUTPUT_NOT_WRITABLE`, exit 2, no partial files

#### Scenario: AC-62
- **WHEN** The run folder name already exists
- **THEN** `RUN_FOLDER_EXISTS`, exit 2; the existing folder is untouched

#### Scenario: AC-63
- **WHEN** A failure after some files were written, without and with `--debug`
- **THEN** Nothing published, previous runs untouched, a message naming the stage and the file; the temporary folder is deleted, or kept as `failed_YYYY-MM-DD_HHMMSSZ` with `--debug`; the log remains

#### Scenario: AC-64
- **WHEN** an unexpected internal error in a stage
- **THEN** `INTERNAL_ERROR` naming the stage, exit 5, no traceback, nothing published

#### Scenario: AC-65
- **WHEN** Memory above 50% and then above 80% of total, and an unknown total
- **THEN** `MEMORY_WARNING`, then `MEMORY_LIMIT` with exit 4 and nothing published; an unknown total gives `MEMORY_TOTAL_UNKNOWN` and skips the check

#### Scenario: AC-66
- **WHEN** Run files on a system with POSIX permissions, and on one without
- **THEN** Folder and files readable only by the owner; otherwise `PERMISSIONS_SKIPPED` in the log

#### Scenario: AC-67
- **WHEN** The log of a run with rejected rows
- **THEN** No card, name, email or phone value appears in the log

### Requirement: Volume
A synthetic file of 100,000 records SHALL run to completion with the duration and peak memory of each stage in the run summary.

#### Scenario: AC-68
- **WHEN** A synthetic file of 100,000 records
- **THEN** The run completes; the summary holds the duration and peak memory of each stage; totals reconcile
