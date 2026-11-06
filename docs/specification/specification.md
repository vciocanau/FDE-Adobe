# Specification: customer data ingestion (CRM loyalty profiles)

## 1. Purpose and scope

The program reads one CRM customer-profile CSV export of a supermarket chain with a loyalty card, cleans and validates it, and publishes a canonical customer table with export-time campaign eligibility, together with rejected rows, duplicates, warnings and a run summary. The end user is the data analyst who prepares the marketing database; the output is also a contract for a later orchestrator.

Out of scope: other sources, sending messages, a live AI model, matching people without a card, and encryption (brainstorming, section 6). Each rule refers to the assumption or decision behind it (A1 to A10, D1 to D30) in `docs/brainstorming/brainstorming.md`, where every item is labelled Given, Assumed or Chosen.

## 2. Terms

- **Record:** one CSV record; it may span several physical lines. `source_record_number` is its position in the file, not a line number.
- **Destination:** where a record ends up: exactly one of canonical customers, rejected rows, or duplicates (as a losing row).
- **Canonical customer:** the winning row for one card.
- **Consent:** agreement to the processing of personal data (GDPR).
- **Subscription:** agreement to receive marketing, newsletter or information messages.
- **Contact channel:** a valid email, a valid phone, or `app_installed` = `yes`.
- **Eligible for campaign:** consent `yes`, subscription `active` and at least one contact channel, at export time.
- **Warning:** a row warning (one record and field) or a run warning (the whole file); it never changes a destination.
- **Pass-through column:** an input column with no known field, copied unchanged after the fixed columns.
- **Stage:** read, clean, write, verify.
- **Temporary folder, run folder:** the files are written into the temporary folder, which is renamed to the run folder only after verification.

## 3. Command line

The program is one command, `python -m ingest run --input <file.csv>`, and its exit code states the outcome. It requires Python 3.11 or later and nothing else (D18); the README shows how to call it on Windows (`py`) and on macOS and Linux (`python3`). Decision and assumption numbers refer to `docs/brainstorming/brainstorming.md`.

| Argument | Meaning | Default | Source |
| --- | --- | --- | --- |
| `--input` | Path of the CRM CSV export | required | D4 |
| `--output` | Folder in which run folders are created | `./runs` | D28 |
| `--dictionary` | File with the approved synonym mappings | `./mappings/synonyms.json` | D6 |
| `--approve` | Mapping proposal file approved by the analyst, used on the rerun (format in section 5) | none | D6 |
| `--missing-contact-threshold` | Share of canonical customers with no contact channel above which the report says the source probably broke | 3% | A7, D11 |
| `--rejection-threshold` | Share of rejected rows above which the report warns that the rejection rate is unusually high | 10% | D21 |
| `--memory-warn` | Share of total memory that raises a warning | 50% | D15 |
| `--memory-stop` | Share of total memory that stops the run cleanly | 80% | D15 |
| `--debug` | Detailed measurement; keeps the temporary folder after a failure as `failed_YYYY-MM-DD_HHMMSSZ` | off | D14, D17 |

Arguments are checked before any file is read. An unknown argument, a missing `--input` or a threshold outside 0 to 100 stops the run with exit code 2 and a usage message.

| Exit code | Meaning |
| --- | --- |
| 0 | Run succeeded and the run folder is published |
| 1 | Run stopped by a data problem: invalid UTF-8, unclosed quote, missing card column, empty file, header only, two columns for one field, no header, unsupported delimiter |
| 2 | Wrong usage or unreachable file: bad arguments, input path missing or unreadable, output folder not writable, run folder name already exists |
| 3 | Waiting for approval: a mapping proposal file was written; the analyst approves it and runs again (D6) |
| 4 | Stopped by the memory threshold (D15) |
| 5 | Verification failed (`VERIFY_FAILED`) or unexpected internal error; the message names the stage, there is no traceback (D17) |

Exit code 3 is not a failure: nothing is published, and the proposal file names the columns that wait for approval. Every non-zero code prints one operator message naming the stage and, where it applies, the input record or the output file (D17).

## 4. Input contract

The input is one CSV file given with `--input`. It is read strictly: a problem is either diagnosed or the row moves to a named destination, and no value is moved to another column silently (D29).

### File

- Encoding is UTF-8. A BOM at the start is accepted and ignored. A byte that is not valid UTF-8, anywhere in the file, stops the run with `INVALID_UTF8`; nothing is replaced automatically.
- Line endings `LF`, `CRLF` and `CR` are all accepted. A line break inside a quoted field is kept as part of the value.
- A file of zero bytes, or holding only a byte-order mark, stops the run with `INPUT_EMPTY`. A file with a header and no records stops it with `NO_DATA_ROWS`.

### Delimiter

Comma and semicolon are accepted and detected from the header line. If the header line contains both, the one that gives more cells is used; on a tie the run stops with `UNSUPPORTED_DELIMITER`. A tab, a vertical bar or any other delimiter stops the run with the same code.

### Quoting

Fields are read with the standard CSV reader of Python in strict mode, following RFC 4180: a quoted field opens with a quote, a quote inside it is doubled, and delimiters and line breaks inside it are part of the value. A custom reader is not built, to stay within the time budget. Strict mode is required: without it a quote that is never closed is accepted silently and swallows the following records.

- A quoted field that is never closed stops the whole run with `UNCLOSED_QUOTE`, naming the line on which the broken record starts, because it would swallow the records after it.
- Text between a closing quote and the delimiter, for example "abc"def, rejects that record with `BAD_QUOTING`. The record is kept in full in the rejected rows file and the run goes on. The reader goes on with the next record.
- A record that spans more than one physical line is kept and gets the warning `MULTILINE_RECORD`, so that every valid multiline field is visible.
- A record that spans more than 5 physical lines stops the whole run with `UNCLOSED_QUOTE`. Such a record is almost certainly a quote that was never closed and was closed by accident further down, which would swallow valid records without any error. The limit of 5 lines is a guess, fixed in the code and to be confirmed with real data.

Known limitation: a quote in the middle of an unquoted field, such as `5" pipe`, is not flagged. The standard reader keeps it as text in that field, and the rule of that field applies. It does not move values into other columns, but a value with a stray quote can reach the canonical table unnoticed. The risk is accepted to keep the time budget. If the customer's data shows the problem, the remedy is a custom reader that rejects such records with `BAD_QUOTING`.

### Header

The first line is the header. If no cell of it contains a letter, or one cell looks like a card (16 digits), the run stops with `NO_HEADER`. A header cell with no name becomes `column_<position>` and is handled as an unknown column (D27). Unknown columns with the same name get the suffixes `_2`, `_3`, so that none is lost.

### Records

- A completely empty line is not a record: it is skipped and not counted. A line holding only delimiters is a record with every cell empty; it is rejected with `CARD_EMPTY`.
- `rows_received` counts the records of the file, without the header and without empty lines.
- A record with fewer cells than the header is kept. The cells that are present are used, the missing ones are empty, and the warning `SHORT_ROW` is written. A missing card still rejects the record, and a missing consent or subscription is unknown.
- A record with more cells than the header is rejected with `EXTRA_CELLS` when any extra cell holds a value, because the values are probably shifted. When every extra cell is empty, for example a delimiter at the end of the line, the record is kept and the warning `TRAILING_EMPTY_CELLS` is written.
- An empty optional cell, or an empty cell of an unknown column, stays empty and never rejects a record.

### Fields

The names accepted for each field are in section 5; the rules for each value are in section 6.

| Field | Status | If the column is missing |
| --- | --- | --- |
| Loyalty card | required | Run stops with `CARD_COLUMN_MISSING` |
| Consent | needed for eligibility | Every customer is not eligible; strong warning `CONSENT_COLUMN_MISSING` |
| Subscription | needed for eligibility | Every customer is not eligible; strong warning `SUBSCRIPTION_COLUMN_MISSING` |
| Email, phone, app installed | at least one valid channel per customer | Customers without a channel are not eligible, with `NO_CONTACT_CHANNEL`; above the threshold the report says the source probably broke |
| First name, last name, last interaction, last purchase date, last purchase amount | optional | Values are empty |

All results are kept in memory at once (D16).

## 5. Header mapping

Each cell of the header is mapped to a canonical field once per run, after the file is read and before any record is cleaned. A column is never mapped silently by a guess: it is mapped by the dictionary, or by a decision of the analyst.

### Matching names

Names are normalized before they are compared: surrounding spaces removed, letters lowercased, diacritics removed, and spaces, hyphens, dots and underscores ignored. `Loyalty Card`, `loyalty_card` and `LOYALTY-CARD` give the same name. The whole name must match; a part of a name never matches.

### Steps for each column

1. **Dictionary.** A name found in the dictionary maps the column to its field. The run does not stop.
2. **Proposal.** Otherwise the simulated agent proposes a field with a score from 0 to 100 and a reason (D7).
3. **Score bands (A6).** Above 90 is safe and from 60 to 90 needs caution; both are written to the proposal file and the run stops with `MAPPING_PENDING` until the analyst decides. The band informs the analyst and never approves a mapping by itself. Below 60 there is no proposal.
4. **No proposal.** The column is passed through unchanged, after the fixed columns, with the warning `UNKNOWN_COLUMN` (D27). It never blocks the run.

A proposal is not made for a field that another column already has. The outcome for every column is recorded in the `mapping` list of the run summary (section 8). Two columns that end on the same field stop the run with `FIELD_MAPPED_TWICE`.

### Dictionary

The dictionary is the file `mappings/synonyms.json`: for each field, a list of names. Mappings approved by the analyst are added to it (D6). Consent means the GDPR agreement to process personal data; subscription means the agreement to receive marketing, newsletters and information. Both are needed for eligibility (D9). Starting content:

| Field | Starting names |
| --- | --- |
| `card_number` | card\_number, loyalty\_card, card, card\_no, nr\_card, numar\_card |
| `first_name` | first\_name, firstname, given\_name, prenume |
| `last_name` | last\_name, surname, family\_name, nume familie |
| `email` | email, e-mail, email\_address, mail |
| `phone` | phone, phone\_number, mobile, telefon, gsm, tel, mobil, tel mobil |
| `app_installed` | app\_installed, has\_app, aplicatie\_instalata, aplicatie, app |
| `consent` | consent, gdpr\_consent, acord, acord gdpr, gdpr, opt\_in |
| `subscription` | subscription, subscription\_status, newsletter\_status, abonare, newsletter, notificari, promotii, marketing, campanii marketing, marketing\_consent |
| `last_interaction_at` | last\_interaction, last\_activity, last\_contact, ultima\_interactiune |
| `last_purchase_at` | last\_purchase, last\_order\_date, ultima\_achizitie |
| `last_purchase_amount` | last\_purchase\_amount, amount\_spent, total\_spent, suma\_cheltuita, valoare bon, total bon |

Because dots and spaces are ignored, `tel.` and `tel`, or `Tel. Mobil` and `tel mobil`, are the same name. The names `marketing`, `marketing_consent` and `opt_in` can mean something else in a real CRM and are confirmed with the customer.

### Simulated agent

There is no API key, so the agent is simulated with fixed answers and the dictionary (D8). It receives only the column names and up to 3 sample values per column, never complete rows (D24). Sample values are taken after control characters are removed (6.1) and are masked: letters become `x`, digits become `9`, and other signs stay, so `ion@x.ro` becomes `xxx@x.xx`. Values that belong to the status lists of section 6 (for example `Da`, `Nu`, `Activ`) are not personal data and are shown unmasked. If the agent fails, the run continues with the dictionary only and the warning `MAPPING_AGENT_FALLBACK` is written (D25).

### Proposal file

When at least one column has a proposal, the run writes a proposal file and stops with exit code 3. The file is `mapping_proposals/proposal_YYYY-MM-DD_HHMMSSZ.json` inside the output folder, outside the run folders, because no result is published at that point. It is plain JSON, filled in by hand by the analyst, and carries a `schema_version` and a `proposal_id` so that an orchestrator can read it and show a form in the future. That integration is not built.

```json
{
  "schema_version": 1,
  "proposal_id": "proposal_2026-11-04_203045Z",
  "input_file": "crm_export.csv",
  "proposals": [
    { "column": "NrCl", "field": "card_number", "score": 94, "band": "safe",
      "reason": "name looks like a client card", "decision": "", "use_field": "" },
    { "column": "C7", "field": null, "score": 41, "band": "none",
      "reason": "no clear match", "decision": "", "use_field": "" }
  ]
}
```

The analyst writes one of three decisions for each proposal:

| Decision | Effect |
| --- | --- |
| `approve` | The proposed field is applied and saved in the dictionary |
| `reject` | The column is passed through unchanged as an unknown column |
| `change` | The field written in `use_field` is applied and saved in the dictionary; an unknown field name stops the run with `USAGE` |

Columns with a score below 60 are listed too, with `field` empty, so that the analyst can map them with `change` if the meaning is known. They do not block the run, and if left empty they are passed through. A proposal with a score of 60 or more and no decision stops the run again with `MAPPING_PENDING`. The analyst runs again with `--approve <file>` (section 3). An approval file that is not a JSON object with a `proposals` list of entries stops the run with `USAGE` before the input is read.

### Out of contract

Some format changes cannot be detected and are confirmed with the customer. A column that keeps its name but changes its meaning is read with the old meaning. Merged or split columns, for example one name column instead of first and last name, are passed through unchanged with `UNKNOWN_COLUMN` (D27), and the fixed fields they replace stay empty. A file with no header, or with a delimiter other than comma or semicolon, stops the run (section 4).

## 6. Field rules

### 6.1 Control character

A control character is any Unicode character of category Cc except TAB (U+0009), LF (U+000A) and CR (U+000D); those three count as whitespace. Before any field rule is applied, control characters are removed from every field value. The rest of the value then follows the field's own rule, as if the control characters had not been there. If any was removed, the row gets the warning `CONTROL_CHARACTER_REMOVED`, which names the field. The same rule applies to the column names in the header, before they are matched (section 5); the warning then names the column in `field`. Nothing else is changed or guessed.

### 6.2 Card number (`card_number`)

1. All whitespace and dashes are removed.
2. An empty result is rejected with `CARD_EMPTY`.
3. A result that is not exactly 16 digits (ASCII 0-9 only) is rejected with `CARD_INVALID`. This covers letters, other lengths, digits from other Unicode scripts and Excel scientific notation such as `1.23457E+15`.
4. The value is kept as text, so leading zeros survive. The same card written with or without spaces gives the same key.

### 6.3 Names (`first_name`, `last_name`)

1. The value is trimmed, and inner whitespace runs become a single space.
2. The value is normalized to Unicode NFC.
3. Cedilla ş ţ Ş Ţ are converted to comma-below ș ț Ș Ț. Letter case and other diacritics are kept.
4. An empty name stays empty, with no warning and no rejection. A name made only of control characters becomes empty, with the warning `CONTROL_CHARACTER_REMOVED`.

### 6.4 Phone (`phone`)

1. An empty value stays empty, with no warning. A phone is optional, and an empty phone is not a valid contact channel.
2. Everything except digits and a leading plus sign is removed (spaces, dashes, dots, brackets).
3. A number starting with `0040` or `+40` becomes `+40` followed by the rest.
4. A number starting with a single `0` becomes `+40` followed by the rest after that `0`.
5. A nine-digit number starting with `7` is read as a Romanian mobile number whose leading `0` was lost when the file was edited in Excel. It becomes `+40` followed by the number, with the warning `PHONE_LEADING_ZERO`.
6. A number with another country prefix is kept as given.
7. If the result has fewer than 8 or more than 15 digits, it is emptied with the warning `PHONE_INVALID`.
8. A phone that is kept is a valid contact channel (see D11). The default prefix `+40` and the lost leading `0` are assumptions to confirm with the customer.

Examples: `0722123456`, `722123456`, `0040722123456` and `+40722123456` all give `+40722123456`, and the nine-digit form adds the warning; `12345` is emptied with the warning.

### 6.5 Email (`email`)

1. An empty value stays empty, with no warning. An email is optional, and an empty email is not a valid contact channel.
2. The value is trimmed and converted to lowercase.
3. The email is valid only if it has no spaces, exactly one `@` and at least one dot after the `@`.
4. An invalid email is emptied with the warning `EMAIL_INVALID`; the row is kept.
5. An email that is kept is a valid contact channel (see D11).

Examples: `Ana@Example.COM` with surrounding spaces gives `ana@example.com`; `ana @example.com`, `ana@@example.com` and `ana@example` are emptied with the warning.

### 6.6 Dates (`last_interaction_at`, `last_purchase_at`)

1. An empty value stays empty, with no warning.
2. The day always comes first. Accepted date formats are ISO 8601 (`2026-11-04`), `DD.MM.YYYY` and `DD/MM/YYYY`. `MM/DD/YYYY` is not accepted, because it is ambiguous.
3. A date can be followed by a time, `HH:MM` or `HH:MM:SS`, separated by a space or by `T` (`2026-11-04 14:30`). An ISO 8601 value may also end with `Z` or an offset such as `+02:00`.
4. A value that matches none of these formats, or is not a real calendar date (`13.13.2026`, `31.02.2026`), is emptied with the warning `TIMESTAMP_UNREADABLE`.
5. A value outside the range that can be converted to UTC (for example year 0001 with an offset) is emptied with the warning `TIMESTAMP_OUT_OF_RANGE`.
6. A value later than the time of the run is emptied with the warning `TIMESTAMP_IN_FUTURE`.
7. A value with a time but no time zone is read in local time. If it falls in the hour that repeats when daylight saving time ends, or in the hour that is skipped when it starts, it is kept and the row gets the warning `TIMESTAMP_AMBIGUOUS_HOUR`. The check needs the time-zone database: Linux and macOS have it; Windows needs the optional `tzdata` package and the `TZ` environment variable set to the zone name (for example `Europe/Bucharest`). Without them the check is skipped and the run continues (D18).
8. A valid value is stored in ISO 8601: `YYYY-MM-DD` for a date alone, `YYYY-MM-DDTHH:MM:SS` for a date with a time, with the offset when the value had one. When timestamps are compared (duplicates, future check), a date alone counts as 00:00:00 local time.
9. In every case the profile is kept; only the field is emptied.

Examples: `2026-11-04`, `04.11.2026` and `04/11/2026` give the same stored value; `11/13/2026` and `13.13.2026` are emptied with the warning.

### 6.7 Consent (`consent`)

Consent is the customer's agreement to the processing of personal data (GDPR). It is not the agreement to receive marketing; that is the subscription (6.8).

1. The value is trimmed and compared in lowercase. Spaces, hyphens and dots between letters are ignored. The whole value is compared, so `nu accept` is not read as `accept`.
2. Read as `yes`: `da`, `yes`, `y`, `true`, `1`, `accept`, `acept`, `accepted`, `opt-in`, `optin`, `ok`.
3. Read as `no`: `nu`, `no`, `n`, `false`, `0`, `refuz`, `refuzat`, `refused`, `opt-out`, `optout`, `retras`, `withdrawn`, `revoked`, `nu doresc`.
4. Anything else, including an empty value, is `unknown`, with the warning `CONSENT_UNKNOWN`. The profile is kept and is not eligible for campaigns.
5. These lists apply only to consent and are not reused for the subscription.
6. The value `ok` is ambiguous, because a CRM may use it as a technical status. It stays in the list and is to be confirmed with the customer.
7. A missing consent column is handled for the whole file: every customer is not eligible, with `CONSENT_COLUMN_MISSING`.

### 6.8 Subscription (`subscription`)

Subscription is the customer's agreement to receive marketing, newsletter or information messages. It is separate from consent (6.7).

1. The value is trimmed and compared in lowercase. The whole value is compared.
2. Read as `active`: `active`, `activ`, `subscribed`, `yes`, `da`, `y`, `true`, `1`.
3. Read as `inactive`: `inactive`, `inactiv`, `unsubscribed`, `no`, `nu`, `n`, `false`, `0`.
4. Anything else, including an empty value, is `unknown`, with the warning `SUBSCRIPTION_UNKNOWN`.
5. An `inactive` or `unknown` subscription does not reject the profile: it stays in the canonical table and is not eligible for campaigns, with the reason.
6. These lists apply only to the subscription and are not reused from consent. The source meanings, scope and mappings are to be confirmed with the customer before use.
7. A missing subscription column is handled for the whole file: every customer is not eligible, with `SUBSCRIPTION_COLUMN_MISSING`.

### 6.9 App installed (`app_installed`)

1. The value is trimmed and compared in lowercase. The whole value is compared.
2. Read as `yes`: `yes`, `da`, `y`, `true`, `1`, `installed`.
3. Read as `no`: `no`, `nu`, `n`, `false`, `0`.
4. Anything else, including an empty value, is `unknown`, with the warning `APP_INSTALLED_UNKNOWN`.
5. Only `yes` counts as a valid contact channel (see D11); `no` and `unknown` do not.

### 6.10 Last purchase amount (`last_purchase_amount`)

The amount is assumed to be the value of the last receipt, not the total spent over the whole relationship. This is to be confirmed with the analyst, together with the currency: the amount is read as a plain number and the currency is neither read nor stored, because the customers may not all be in Romania.

1. An empty value stays empty, with no warning.
2. The value is trimmed. A value with a currency symbol or code, or any other text, is invalid.
3. A number may use a dot or a comma as the decimal separator, and only when exactly one separator is present and is followed by 1 or 2 digits (`12.50`, `12,5`). Thousands separators are not accepted, so `1,234` and `1.234,50` are invalid, because they are ambiguous.
4. A negative amount is invalid.
5. Zero is invalid.
6. An invalid value is emptied with the warning `PURCHASE_AMOUNT_INVALID`; the profile is kept.
7. A valid amount is stored with a dot as the decimal separator, as written (`12,5` is stored as `12.5`), without rounding.

Examples: `12.50`, `12,50` and `12.50` with surrounding spaces give `12.50`; `-12.50`, `0`, `12 lei`, `1,234` and `abc` are emptied with the warning.

## 7. Row processing

Every input record gets exactly one destination: canonical customers, rejected rows, or duplicates (as a losing row). Warnings never change the destination and are not counted as rows.

### 7.1 Order of steps

1. The record is read (section 4). A record with a value in an extra cell (`EXTRA_CELLS`) or text after a closing quote (`BAD_QUOTING`) is rejected here.
2. The field rules (section 6) are applied to every field of the remaining records.
3. A record with an empty or invalid card is rejected (`CARD_EMPTY`, `CARD_INVALID`). It never enters the canonical table, whatever consent or contact data it carries. All its errors go in one line of the rejected rows file.
4. Records with a valid card are grouped by card number. A group of one is a canonical customer; a group of several goes through 7.2.
5. Eligibility is computed for each canonical customer (7.3).

### 7.2 Duplicates

1. The winner is the row with the most recent valid `last_interaction_at`. A valid timestamp beats a missing or invalid one. If timestamps tie, or all are unusable, the later record in the input wins, with the warning `DUPLICATE_TIE`.
2. In a group of more than two rows there is one winner, and every other row is compared with it.
3. `consent` and `subscription` come only from the winning row and are never combined across rows.
4. Losing rows go to `duplicates.csv` with the reason `LOST_OLDER_TIMESTAMP`, `LOST_INVALID_TIMESTAMP` or `LOST_TIE_LATER_ROW_WINS`.
5. If the timestamps cannot decide (one is missing or invalid, or they tie) and the winner and that losing row disagree on consent or subscription, the customer is not eligible with the reason `CONFLICTING_DUPLICATES` and the warning `DUPLICATE_CONFLICT`.
6. Eligibility is computed after the winner is chosen.

### 7.3 Eligibility

`eligible_for_campaign` is `yes` only if consent is `yes`, subscription is `active` and there is at least one valid contact channel (a valid email, a valid phone, or `app_installed` = `yes`). Otherwise it is `no`, and `ineligibility_reasons` lists every reason that applies: `CONSENT_NOT_YES` (no or unknown), `SUBSCRIPTION_NOT_ACTIVE`, `NO_CONTACT_CHANNEL`, `CONFLICTING_DUPLICATES`. When the consent or subscription column is missing from the file, the reason is `CONSENT_COLUMN_MISSING` or `SUBSCRIPTION_COLUMN_MISSING` instead of `CONSENT_NOT_YES` or `SUBSCRIPTION_NOT_ACTIVE`. The result is eligibility at export time, not a send authorization (D12).

### 7.4 Totals and thresholds

1. received = canonical + rejected + duplicate losing. This is checked in stage 4, before anything is published; a mismatch fails the run with `VERIFY_FAILED`.
2. If more than 3% of canonical customers have no valid contact channel, the run gets the warning `MISSING_CONTACT_THRESHOLD`. If more than 10% of received rows are rejected, the run gets `REJECTION_RATE_HIGH`. Both thresholds are configurable, and the effective values are written in the summary.

## 8. Output contract

A successful run publishes one run folder with five files. The folder is named `run_YYYY-MM-DD_HHMMSSZ` in UTC, so that folders sort in time order and the repeated hour at the end of daylight saving time cannot give two runs the same name, for example `run_2026-11-04_163045Z` (D28). Files are first written into a temporary folder in the same output folder and the folder is renamed only after verification (D12). Run folder and files are created readable only by their owner where the operating system supports it (D26).

| File | Content | Format |
| --- | --- | --- |
| `canonical_customers.csv` | One row per winning customer, eligible or not | CSV |
| `rejected_rows.csv` | One row per rejected input row | CSV |
| `warnings.csv` | One row per warning | CSV |
| `duplicates.csv` | One row per duplicate losing row | CSV |
| `run_summary.json` | Totals, thresholds, flags, time and memory per stage | JSON |

All CSV files use UTF-8 without a BOM, a comma as delimiter, a header row even when empty, and quoting for any value that holds a comma, a quote or a line break (D30). Timestamps are ISO 8601. Lists of codes inside one cell are separated by `;`. `source_record_number` is the number of the data record in the input, counted from 1 and not counting the header; it is not a physical line number, because a quoted field can span lines.

### canonical\_customers.csv

| Column | Content |
| --- | --- |
| `card_number` | 16 digits, kept as text (D3) |
| `first_name`, `last_name` | Cleaned names, possibly empty (D22) |
| `email` | Lowercased email, or empty |
| `phone` | Phone in the form `+<country><number>`, or empty |
| `app_installed` | `yes`, `no` or `unknown` |
| `consent` | `yes`, `no` or `unknown` |
| `subscription` | `active`, `inactive` or `unknown` |
| `last_interaction_at` | ISO 8601 timestamp, or empty |
| `last_purchase_at` | ISO 8601 timestamp, or empty |
| `last_purchase_amount` | Decimal number with a dot and no currency symbol, or empty |
| `eligible_for_campaign` | `yes` or `no`: eligibility at export time (D9), not a send authorization (D12) |
| `ineligibility_reasons` | Codes separated by `;`, empty when eligible: `CONSENT_NOT_YES`, `SUBSCRIPTION_NOT_ACTIVE`, `NO_CONTACT_CHANNEL`, `CONFLICTING_DUPLICATES`, `CONSENT_COLUMN_MISSING`, `SUBSCRIPTION_COLUMN_MISSING` |
| `source_record_number` | Record number of the winning row |

Pass-through columns (D27) follow these columns unchanged, in the order of the input.

### rejected\_rows.csv

| Column | Content |
| --- | --- |
| `source_record_number` | Record number |
| `reason_codes` | All reasons, separated by `;`, codes from section 9 |
| `reason_text` | The same reasons in plain words, separated by `;` |
| `original_row` | The input record in full, as read, without control characters (6.1); it contains personal data (D26) |

Each rejected row is one line, whatever the number of its reasons.

### warnings.csv

| Column | Content |
| --- | --- |
| `source_record_number` | Record number; empty for a warning about the whole run or a column |
| `field` | Field or column name the warning concerns; empty for a whole-run warning |
| `code` | Warning code from section 9 |
| `message` | Plain-language message |

### duplicates.csv

| Column | Content |
| --- | --- |
| `card_number` | The card shared by the rows |
| `source_record_number` | Losing row |
| `last_interaction_at` | Timestamp of the losing row, or empty |
| `kept_record_number` | Winning row |
| `reason` | Why this row lost, code from section 9 |

### run\_summary.json

The summary carries the schema version, which the orchestrator must check before reading the other files. A change to any column of the files above raises it. Percentages are numbers, named with the suffix `_pct`. The model below shows the structure; its numbers are examples.

```json
{
  "schema_version": 1,
  "run_id": "run_2026-11-04_163045Z",
  "run_started_at": "2026-11-04T18:30:45+02:00",
  "export_date": "2026-11-04",
  "input": { "file": "crm_export.csv", "rows_received": 100000 },
  "mapping": [
    { "column": "Loyalty Card", "field": "card_number", "source": "dictionary" },
    { "column": "NrCl", "field": "card_number", "source": "approved" },
    { "column": "Religie", "field": null, "source": "passed_through" }
  ],
  "destinations": {
    "canonical": 99100,
    "rejected": 300,
    "duplicate_losing": 600,
    "reconciled": true
  },
  "eligibility": {
    "eligible": 81000,
    "not_eligible": 18100,
    "reasons": { "CONSENT_NOT_YES": 9000, "SUBSCRIPTION_NOT_ACTIVE": 7000, "NO_CONTACT_CHANNEL": 100 }
  },
  "warnings": { "total": 845, "by_code": { "SHORT_ROW": 12, "PHONE_LEADING_ZERO": 40 } },
  "stages": {
    "read":   { "duration_ms": 570,  "peak_memory_mb": 210 },
    "clean":  { "duration_ms": 800,  "peak_memory_mb": 390 },
    "write":  { "duration_ms": 1100, "peak_memory_mb": 400 },
    "verify": { "duration_ms": 300,  "peak_memory_mb": 400 }
  },
  "total_duration_ms": 2800,
  "total_memory_mb": 16384,
  "thresholds": {
    "missing_contact_pct": 3,
    "rejection_pct": 10,
    "memory_warn_pct": 50,
    "memory_stop_pct": 80
  },
  "observed": { "missing_contact_pct": 0.1, "rejection_pct": 0.3 },
  "flags": { "source_probably_broke": false, "rejection_rate_high": false }
}
```

`export_date` is the modification date of the input file. `total_memory_mb` is `null` when the total cannot be read, and the memory check is then skipped with a warning (D15). `total_duration_ms` is measured over the whole run and is a separate value from the stage durations (D14). Durations are measured with a monotonic clock, so a change of the clock, such as the end of daylight saving time, does not distort them. The `mapping` list gives, for each input column, the field it was mapped to and where the decision came from: `dictionary` (a name in the dictionary), `approved` (a proposal approved or changed by the analyst) or `passed_through` (not recognized, passed through unchanged). It lets a reader trace any field back to its source column.

## 9. Errors and warnings

Every problem has a code written in capitals. A code decides where the problem is reported, whether the row moves, and whether the run goes on. A warning never changes the destination of a row (brainstorming, section 2); only a rejection reason, a duplicate loss or a stop does.

### Run errors

A run error stops the run and prints one line: `ERROR <CODE> [stage <name>] <message>`, with the input record number or the file name where it applies. Nothing is published (D17).

| Code | Exit | Stage | Message | Cause |
| --- | --- | --- | --- | --- |
| `USAGE` | 2 | start | Wrong arguments: \<detail>. Usage: python -m ingest run --input \<file.csv> | Unknown or missing argument, threshold outside 0 to 100 |
| `INPUT_NOT_FOUND` | 2 | read | Input file not found: \<path> | Path does not exist |
| `INPUT_UNREADABLE` | 2 | read | Input file cannot be read: \<path> (\<reason>) | No permission or a directory |
| `OUTPUT_NOT_WRITABLE` | 2 | write | Output folder cannot be written: \<path> (\<reason>) | No permission, read-only disk, a file in the way |
| `RUN_FOLDER_EXISTS` | 2 | write | Run folder already exists: \<path>; nothing was overwritten | Same name in the same second |
| `INPUT_EMPTY` | 1 | read | Input file is empty (0 bytes): \<path> | Zero-byte file |
| `NO_DATA_ROWS` | 1 | read | Input has a header but no data rows | Header only, or header and blank rows |
| `NO_HEADER` | 1 | read | The first line does not look like a header | First line holds data such as a card number |
| `UNSUPPORTED_DELIMITER` | 1 | read | Delimiter not supported; accepted delimiters are comma and semicolon | Any other delimiter in the header line |
| `INVALID_UTF8` | 1 | read | Input is not valid UTF-8 (near record \<n>); save the file as UTF-8 | Wrong encoding; nothing is replaced |
| `UNCLOSED_QUOTE` | 1 | read | A quoted field is never closed; the broken record starts on line \<n> | Missing closing quote that would swallow the rows after it, or one record spanning more than 5 lines |
| `CARD_COLUMN_MISSING` | 1 | map | No column was recognized as the loyalty card number | Header has no card column, even after mapping |
| `FIELD_MAPPED_TWICE` | 1 | map | Columns \<a> and \<b> both map to \<field>; choose one | Two columns claim one field |
| `MAPPING_PENDING` | 3 | map | Mapping proposal written to \<path>; approve it and run again with --approve | A new or renamed column has a proposal; waits for the analyst |
| `MEMORY_LIMIT` | 4 | any | Memory use passed \<n>% of total memory; run stopped (or: Memory ran out in stage \<name>; run stopped) | `--memory-stop` threshold reached, or the system refused memory before a check could stop the run |
| `VERIFY_FAILED` | 5 | verify | Verification failed: \<detail>; nothing was published | Totals do not reconcile, or a written file does not match |
| `INTERNAL_ERROR` | 5 | any | Unexpected error in stage \<name>; see the log | Any other failure; no traceback is printed |

### Rejection reasons

Written in `reason_codes` of `rejected_rows.csv`. A row can have several; all that apply are listed.

| Code | Plain text | Cause |
| --- | --- | --- |
| `CARD_EMPTY` | Loyalty card is empty | No value in the card column |
| `CARD_INVALID` | Loyalty card is not 16 digits | After removing spaces and dashes, any other length or any non-digit |
| `EXTRA_CELLS` | Row has more cells than the header and an extra cell holds a value | Stray separator; the row is kept in full in `original_row` (D29) |
| `BAD_QUOTING` | Row has text after a closing quote | Text after a closing quote; values could be shifted (section 4) |

### Duplicate reasons

Written in `reason` of `duplicates.csv`.

| Code | Meaning |
| --- | --- |
| `LOST_OLDER_TIMESTAMP` | The winning row has a more recent valid interaction timestamp |
| `LOST_INVALID_TIMESTAMP` | This row has a missing or invalid timestamp and the winner has a valid one |
| `LOST_TIE_LATER_ROW_WINS` | Timestamps tie or both are unusable, and the later row in the input won |

### Warnings

Written in `warnings.csv`. Row warnings carry the record number and the field; run warnings leave both empty, except `UNKNOWN_COLUMN`, which names the column in `field`. A strong warning is also written to the log at warning level with its code.

| Code | Level | Message | Effect |
| --- | --- | --- | --- |
| `SHORT_ROW` | row | Row has fewer cells than the header; missing cells are empty | Row kept |
| `CONTROL_CHARACTER_REMOVED` | row | A control character was removed from a field value; the warning names the field | Control character removed, value kept |
| `EMAIL_INVALID` | row | Email is not valid and was emptied | Field emptied; counts as no email channel |
| `PHONE_INVALID` | row | Phone is not valid and was emptied | Field emptied; counts as no phone channel |
| `PHONE_LEADING_ZERO` | row | Phone has nine digits and starts with 7; a lost leading 0 is assumed (A10) | Phone kept as +40 and the number |
| `TIMESTAMP_UNREADABLE` | row | Timestamp cannot be read and was emptied | Field emptied |
| `TIMESTAMP_OUT_OF_RANGE` | row | Timestamp is outside the range that can be converted and was emptied | Field emptied |
| `TIMESTAMP_IN_FUTURE` | row | Timestamp is later than the run time and was emptied | Field emptied |
| `TIMESTAMP_AMBIGUOUS_HOUR` | row | Timestamp without a time zone falls in an hour that repeats or does not exist; local time is assumed | Value kept |
| `PURCHASE_AMOUNT_INVALID` | row | Last purchase amount is not a valid number, is negative or is zero and was emptied | Field emptied |
| `CONSENT_UNKNOWN` | row | Consent value is empty or not recognized | Consent unknown; not eligible |
| `SUBSCRIPTION_UNKNOWN` | row | Subscription value is empty or not recognized | Subscription unknown; not eligible |
| `APP_INSTALLED_UNKNOWN` | row | App installed value is empty or not recognized | Unknown; no app channel |
| `NO_CONTACT_CHANNEL` | row, strong | Profile has no valid email, phone or app channel (D11) | Kept; not eligible; counted toward the 3% threshold |
| `DUPLICATE_CONFLICT` | row, strong | Duplicates disagree on consent or subscription and the order is unknown (D20) | Customer not eligible |
| `DUPLICATE_TIE` | row | Timestamps tie or are unusable; the later row won | Later row kept |
| `UNKNOWN_COLUMN` | run | Column \<name> is not recognized and is passed through unchanged (D27) | Column kept after the fixed columns |
| `CONSENT_COLUMN_MISSING` | run, strong | No consent column; every customer is not eligible | All customers not eligible |
| `SUBSCRIPTION_COLUMN_MISSING` | run, strong | No subscription column; every customer is not eligible | All customers not eligible |
| `MISSING_CONTACT_THRESHOLD` | run, strong | More than \<n>% of canonical customers have no contact channel; the source probably broke | Run goes on; flag in summary |
| `REJECTION_RATE_HIGH` | run | More than \<n>% of rows were rejected; the rate is unusually high and the source is worth checking | Run goes on; flag in summary |
| `MEMORY_WARNING` | run | Memory use passed \<n>% of total memory | Run goes on |
| `MEMORY_TOTAL_UNKNOWN` | run | Total memory cannot be read; the memory check is skipped | Run goes on |
| `MAPPING_AGENT_FALLBACK` | run | The mapping agent failed; the synonym dictionary was used | Run goes on |
| `PERMISSIONS_SKIPPED` | run | File permissions cannot be restricted on this system | Run goes on |
| `TRAILING_EMPTY_CELLS` | row | Row has more cells than the header, and all extra cells are empty | Row kept; extra cells dropped |
| `MULTILINE_RECORD` | row | Record spans more than one line; check that a quote was not closed by accident | Row kept |

Codes used in the log follow the same names. A code is never reused for another meaning, and a new code is added to this section before it is used.

## 10. Operations

### 10.1 Log

1. Each run writes its log to the console (stderr) and to `<output>/logs/run_YYYY-MM-DD_HHMMSSZ.log`, named like the run folder. The log lives outside the run folder, so it survives a failed run (D17).
2. One line per event: UTC time, level (`INFO`, `WARNING`, `ERROR`), stage, code (section 9), message.
3. `INFO`: start and end of each stage with its duration and peak memory, and the counts at the end of the run. `WARNING`: every run warning and every strong row warning (section 9). `ERROR`: the run error.
4. The log holds no personal data: no card, name, email or phone values. Rows are referred to by `source_record_number` (D26).
5. With `--debug`, the log also records progress every 10,000 records and memory at each check, and the temporary folder is kept after a failure (D17).

### 10.2 Duration

Each stage (read, clean, write, verify) and the whole run are timed with a monotonic clock. Durations go into the summary and the log.

### 10.3 Memory

1. The peak memory of the process is checked at the end of each stage, and every 10,000 records during read and clean.
2. Peak of the process: on Linux and macOS through `resource.getrusage` (`ru_maxrss`, in KiB on Linux and in bytes on macOS); on Windows through `GetProcessMemoryInfo` (`PeakWorkingSetSize`) via `ctypes`.
3. Total memory: on Linux from `/proc/meminfo`; on macOS from `sysctl -n hw.memsize`; on Windows from `GlobalMemoryStatusEx` via `ctypes`.
4. A peak above `--memory-warn` (default 50%) gives `MEMORY_WARNING`, once. A peak above `--memory-stop` (default 80%) stops the run with `MEMORY_LIMIT` and exit code 4; nothing is published.
5. If the total cannot be read, the run gets `MEMORY_TOTAL_UNKNOWN`, the thresholds are skipped and `total_memory_mb` is `null`.
6. The Windows reading is verified on a Windows machine before delivery.

Before the input is read, the peak is estimated as 40 MB of memory per MB of input file; the measured ratio was 39 on the 100,000-record run and 29 on the 1,000,000-record run, rounded up to stay safe. If the estimate is above `--memory-stop` of total memory, the run stops at once with `MEMORY_LIMIT` and exit code 4, without reading the file and without publishing anything. When the total cannot be read, the estimate is skipped. Without this estimate a file too large to load ends the process before the first check at record 10,000, so the stop above could not happen.

If the system refuses memory during a run before a check could stop it (Python raises `MemoryError`), the run stops with `MEMORY_LIMIT` and exit code 4, with the message `Memory ran out in stage <name>; run stopped`; nothing is published. On some systems the process is ended by the operating system before this can be reported, so the estimate above remains the main protection.

## 11. Acceptance cases

Each case becomes an automated test with a fixed expected result, and the work is not done until every test passes. Related cases may share one parametrized test. The cases come from the brainstorming (section 7) and follow the rules in sections 4 to 10 of this specification. Exit codes are in section 3 and codes in section 9.

### 11.1 Reading the file

| ID | Input | Expected result |
| --- | --- | --- |
| AC-01 | Input path does not exist | `INPUT_NOT_FOUND` naming the path, exit 2, no result files, no traceback |
| AC-02 | Input file exists but cannot be read (no permission) | `INPUT_UNREADABLE` naming the file and the reason, exit 2, no result files |
| AC-03 | Empty file (zero bytes) | `INPUT_EMPTY`, exit 1, no result files |
| AC-04 | Header only, and a header followed only by blank rows | `NO_DATA_ROWS`, exit 1, no result files |
| AC-05 | First line holds a card number instead of column names | `NO_HEADER`, exit 1, no result files |
| AC-06 | A file with semicolons, and a file with tabs | The semicolon file gives the same result as the comma file; the tab file stops with `UNSUPPORTED_DELIMITER`, exit 1, naming the accepted delimiters |
| AC-07 | Invalid UTF-8 in the header, and invalid UTF-8 in a record further down | `INVALID_UTF8`, exit 1, nothing replaced, no result files |
| AC-08 | File that starts with a BOM | Read normally; the first column name has no hidden character |
| AC-09 | The same file with LF, CRLF and CR line endings | Identical results |
| AC-10 | A row with extra cells that are all empty, and a row with a value in an extra cell | The first is kept with `TRAILING_EMPTY_CELLS`; the second is rejected with `EXTRA_CELLS`, kept in full with its `source_record_number`; the run continues; totals reconcile |
| AC-11 | A row with fewer cells than the header | Kept, missing cells empty, `SHORT_ROW`; a missing card rejects the row (`CARD_EMPTY`); a missing consent or subscription is `unknown`; totals reconcile |
| AC-12 | Optional and pass-through cells empty in some rows, filled in others | Filled values kept, empty cells stay empty, no row rejected for that |
| AC-13 | Text right after a closing quote (`"abc"def`) | That row alone is rejected with `BAD_QUOTING`; the run continues |
| AC-14 | A quoted field that closes correctly after 2 to 5 physical lines | Row kept with `MULTILINE_RECORD` |
| AC-15 | A quote that is never closed | `UNCLOSED_QUOTE` naming the line where the record started, exit 1, nothing published |
| AC-16 | A quote closed by accident further down, merging rows over 15 lines | `UNCLOSED_QUOTE` naming the line where the record started, exit 1, nothing published |
| AC-17 | A quote in the middle of an unquoted field (`ab"c`) | Read as text without an error (the documented known limitation) |

### 11.2 Header mapping

| ID | Input | Expected result |
| --- | --- | --- |
| AC-18 | No column maps to the card | `CARD_COLUMN_MISSING`, exit 1, no result files |
| AC-19 | Two columns map to the same field | `FIELD_MAPPED_TWICE`, exit 1, nothing guessed |
| AC-20 | A column with an unknown name and no proposal (score below 60) | Passed through after the fixed columns, `UNKNOWN_COLUMN`; the run continues |
| AC-21 | A new column with a proposal scoring above 90, and one scoring 60 to 90 | The run stops with `MAPPING_PENDING`, exit 3, and writes a proposal file showing the band; nothing is approved automatically; columns below 60 are listed with an empty field |
| AC-22 | Rerun with `--approve` after decisions approve, reject, change to a known field, change to an unknown field | Approved and changed mappings are used and saved in the dictionary; a rejected mapping is passed through with `UNKNOWN_COLUMN`; a change to an unknown field is a `USAGE` error, exit 2 |
| AC-23 | The simulated agent fails | The run falls back to the dictionary with `MAPPING_AGENT_FALLBACK` and does not stop |
| AC-24 | What the agent receives | Column names and at most 3 masked samples per column: letters become `x`, digits become `9`; status values such as `da`, `nu`, `yes`, `active` stay unmasked; no complete row, no unmasked card, email or phone |

### 11.3 Field rules

| ID | Input | Expected result |
| --- | --- | --- |
| AC-25 | A control character in a name, card, email, phone, consent, subscription, app installed and pass-through value | The character is removed, the rest follows the field's rule, `CONTROL_CHARACTER_REMOVED` names the field; written files stay valid |
| AC-26 | Name `Gheorghe` followed by U+0001 | Stored as `Gheorghe` with `CONTROL_CHARACTER_REMOVED`; the row is kept |
| AC-27 | Cards `1234 5678`, `12345678901234AB`, empty, `1.23457E+15` | Rejected: `CARD_INVALID`, `CARD_INVALID`, `CARD_EMPTY`, `CARD_INVALID`; not in the canonical table; totals reconcile |
| AC-28 | A 16-digit card with a control character inside, and a 15-digit card with one | The first is valid with `CONTROL_CHARACTER_REMOVED`; the second is rejected with `CARD_INVALID` |
| AC-29 | Names with cedilla ş ţ and with comma-below ș ț | Both give the identical value |
| AC-30 | A name with extra inner spaces and a decomposed accent | Trimmed, inner spaces collapsed, stored in NFC |
| AC-31 | First name or last name absent or empty | Profile kept with empty names; no rejection |
| AC-32 | Phones `0722123456`, `722123456`, `0040722123456`, `+40722123456`, `12345` | The first four give `+40722123456`; `722123456` adds `PHONE_LEADING_ZERO`; `12345` is emptied with `PHONE_INVALID` |
| AC-33 | Emails `Ana@Example.COM` (with surrounding spaces), `ana @example.com`, `ana@@example.com`, `ana@example` | The first gives `ana@example.com`; the others are emptied with `EMAIL_INVALID` |
| AC-34 | Dates `2026-11-04`, `04.11.2026`, `04/11/2026`, `2026-11-04 14:30`, `11/13/2026`, `13.13.2026`, `31.02.2026` | The first three give the same value; the fourth is kept with its time; the last three are emptied with `TIMESTAMP_UNREADABLE`; the profile is kept |
| AC-35 | Timestamps `0001-01-01T00:00:00+01:00` and one later than the run time | Emptied with `TIMESTAMP_OUT_OF_RANGE` and `TIMESTAMP_IN_FUTURE`; the profile is kept; no crash |
| AC-36 | A timestamp without a zone in the hour that repeats when daylight saving time ends | Kept, read in local time, `TIMESTAMP_AMBIGUOUS_HOUR` |
| AC-37 | Every consent value in the lists, in mixed case and spacing; empty; `nu accept` | Listed values give `yes` or `no`; empty and `nu accept` give `unknown` with `CONSENT_UNKNOWN` |
| AC-38 | Every subscription value in the lists, in mixed case and with surrounding spaces; empty; unrecognized | Listed values give `active` or `inactive`; the others give `unknown` with `SUBSCRIPTION_UNKNOWN` |
| AC-39 | Amounts `12.50`, `12,50`, `-12.50`, `0`, `12 lei`, `1,234`, `abc` | `12.50` and `12,50` give `12.50`; the others are emptied with `PURCHASE_AMOUNT_INVALID`; the profile is kept |

### 11.4 Rows, duplicates and eligibility

| ID | Input | Expected result |
| --- | --- | --- |
| AC-40 | The nine combinations of consent `yes`/`no`/`unknown` and subscription `active`/`inactive`/`unknown`, each with a valid card and email | Only `yes` + `active` is eligible; all nine stay canonical with every reason in `ineligibility_reasons`; unknown states give warnings |
| AC-41 | Consent `yes`, subscription `active`, no valid email, phone or app | Canonical, not eligible, `NO_CONTACT_CHANNEL` as reason and warning; counted for the 3% threshold |
| AC-42 | No consent column, and no subscription column | Every customer not eligible with `CONSENT_COLUMN_MISSING` or `SUBSCRIPTION_COLUMN_MISSING`, and the run warning; all five outputs published |
| AC-43 | Same card twice: the older row eligible, the newer row with consent `no` or subscription `inactive` | The newer row wins; not eligible; the older row in `duplicates.csv` with `LOST_OLDER_TIMESTAMP` |
| AC-44 | Same card twice with the same timestamp, and with both timestamps missing | The later record wins with `DUPLICATE_TIE`; the other has `LOST_TIE_LATER_ROW_WINS` |
| AC-45 | The same card written with spaces in groups of 5, 9 and 2 digits, and without spaces | Same key; the second is handled as a duplicate |
| AC-46 | Same card twice, same states, older row with a real timestamp, newer row in the future | The future timestamp is emptied with `TIMESTAMP_IN_FUTURE`; the real one wins; the other has `LOST_INVALID_TIMESTAMP` |
| AC-47 | Same card twice, one timestamp missing, rows disagree on consent | Not eligible with `CONFLICTING_DUPLICATES` and `DUPLICATE_CONFLICT` |
| AC-48 | Same card twice, same timestamp, rows disagree on subscription | The later record wins; not eligible with `CONFLICTING_DUPLICATES` and `DUPLICATE_CONFLICT` |
| AC-49 | Same card twice, one timestamp missing, rows agree on both states | The row with the valid timestamp wins; no conflict reason |
| AC-50 | Same card three times | One winner; the other two in `duplicates.csv`, each compared with the winner |
| AC-51 | More than 3% of canonical customers without a contact channel, and a file with exactly 3% | Above: `MISSING_CONTACT_THRESHOLD`; at 3%: only the row warnings; both counts in the summary |
| AC-52 | More than 10% of rows rejected | `REJECTION_RATE_HIGH`; the run is not stopped |
| AC-53 | One canonical winner, one losing duplicate, one rejected row | received = canonical + rejected + duplicate losing; warnings are not counted as rows |

### 11.5 Outputs

| ID | Input | Expected result |
| --- | --- | --- |
| AC-54 | A clean file with no rejections, warnings or duplicates | All five files exist; empty CSV files keep their headers; the summary reconciles counts and records the thresholds |
| AC-55 | A rejected row with one error and one with several | One line each, same columns, all errors in one column |
| AC-56 | Output contract of a successful run | The summary holds `schema_version` and `export_date` (modification date of the input file); the canonical table has no schema version column; eligibility is labelled as at export time; no message is sent |
| AC-57 | Summary of a successful run | Duration and peak memory of each of the four stages, total duration, and the `mapping` list with a source for every input column |
| AC-58 | Names with ș and ț written to the CSV files | UTF-8 without a BOM; the names read back identical |
| AC-59 | Two runs one after the other, also one hour apart across the daylight saving change | Each has its own folder named in UTC ending in `Z`; the first folder is untouched |
| AC-60 | The same input run twice | The same files with the same content, apart from run times and durations in the summary |

### 11.6 Failures and operations

| ID | Input | Expected result |
| --- | --- | --- |
| AC-61 | Output folder not writable | `OUTPUT_NOT_WRITABLE`, exit 2, no partial files |
| AC-62 | The run folder name already exists | `RUN_FOLDER_EXISTS`, exit 2; the existing folder is untouched |
| AC-63 | A failure after some files were written, without and with `--debug` | Nothing published, previous runs untouched, a message naming the stage and the file; the temporary folder is deleted, or kept as `failed_YYYY-MM-DD_HHMMSSZ` with `--debug`; the log remains |
| AC-64 | An unexpected internal error in a stage | `INTERNAL_ERROR` naming the stage, exit 5, no traceback, nothing published |
| AC-65 | Memory above 50% and then above 80% of total, and an unknown total | `MEMORY_WARNING`, then `MEMORY_LIMIT` with exit 4 and nothing published; an unknown total gives `MEMORY_TOTAL_UNKNOWN` and skips the check |
| AC-66 | Run files on a system with POSIX permissions, and on one without | Folder and files readable only by the owner; otherwise `PERMISSIONS_SKIPPED` in the log |
| AC-67 | The log of a run with rejected rows | No card, name, email or phone value appears in the log |
| AC-69 | The system refuses memory during a stage | `MEMORY_LIMIT` naming the stage, exit 4, no traceback, nothing published |

### 11.7 Volume

| ID | Input | Expected result |
| --- | --- | --- |
| AC-68 | A synthetic file of 100,000 records | The run completes; the summary holds the duration and peak memory of each stage; totals reconcile |

Two larger runs are measured by hand and are not automated tests, because they take long and depend on the machine. A synthetic file of 1,000,000 records (10x) is run and its real durations and peak memory are written in the README. A synthetic file of 10,000,000 records (100x) is then attempted: either it completes and its figures are written in the README, or it stops cleanly with `MEMORY_LIMIT` (D15), which is documented as the point where row-by-row processing becomes necessary (D16). An extrapolation from the 1x and 10x figures is added as an estimate. The synthetic generator takes the number of records as a parameter.

## 12. Traceability

| Item | Specification section |
| --- | --- |
| A1, A9 | 1 |
| A2 | 6.2 |
| A3 | 6.7, 6.8, 7.3, 8 |
| A4 | 11.7 |
| A5 | 6.7 |
| A6 | 5 |
| A7, A8 | 7.3, 7.4 |
| A10 | 6.4 |
| D1, D2, D18, D19 | 1 |
| D3 | 6.2, 7.1 |
| D4 | 1, 4 |
| D5, D12, D28, D30 | 8 |
| D6, D7, D8, D24, D25 | 5 |
| D9 | 7.3 |
| D10, D22 | 6 |
| D11 | 7.3, 7.4 |
| D13 | 11.7 |
| D14 | 10.1, 10.2 |
| D15 | 10.3 |
| D16 | 4, 11.7 |
| D17 | 3, 9, 10.1 |
| D20 | 7.2 |
| D21 | 4, 7.4, 9 |
| D23 | 7.1 |
| D26 | 8, 10.1 |
| D27 | 5, 8 |
| D29 | 4, 6.1 |

Decisions refined while writing this specification, and updated in `brainstorming.md`: the run folder name is in UTC and ends with `Z` (D28); control characters are removed from every field, with one warning (D29); a zero or negative last purchase amount is invalid (D10); `schema_version` is recorded in the run summary only (D12); consent and subscription are defined separately (section 2).
