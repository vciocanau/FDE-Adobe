# Customer data ingestion for a supermarket loyalty program: assumptions and decisions

Status: draft. Assumptions come first (what is believed about the customer), then decisions (what is built given them). Nothing is approved yet and no code has been written.

## 1. Big picture map

```
Customer wants a clean, canonical audience table from noisy, changing sources
|
+-- 1. CLIENT      analyst prepares a marketing database           -> decided
+-- 2. SOURCE      CRM profile CSV (others considered, left out)   -> decided
+-- 3. CHANGE      format drift, human approves new mappings       -> decided
+-- 4. QUALITY     messy values, consent and subscription rules    -> decided
+-- 5. OPERATIONS  log per stage, memory %, verify, fail clean     -> decided
```

## 2. Flow being built

```
CRM profile CSV (one row per customer, state at export time)

Stage 1  Read
   -> read strictly: extra cells, unclosed quotes, bad encoding are diagnosed, never lost
   -> map headers (dictionary + simulated agent proposal with match score 0-100)
      new column with a proposal: the run stops, writes a mapping proposal file (JSON),
      the analyst approves, rejects or changes each entry and runs again; approved mappings are saved in the dictionary
      new column without a proposal: passed through unchanged, with a warning (D27)

Stage 2  Clean
   -> clean + validate each row (card, names, phone, email, dates, consent, subscription, app values)
   -> a row without a valid card goes to rejected rows (D3)
   -> resolve duplicates by D20, then determine campaign eligibility by D9 and D11
   -> outcome: canonical (eligible or not eligible for campaigns), rejected, or duplicate losing row
   -> warnings are recorded separately and do not change the destination
   -> all results kept in memory (fine at 100,000 rows)

Stage 3  Write
   -> write five files into a temporary folder: canonical customers, rejected rows,
      warnings, run summary, duplicates
   -> canonical customers include both eligible and not eligible profiles, with explicit reasons

Stage 4  Verify
   -> reconcile totals and re-read the written files, still in the temporary folder
   -> only if everything matches: rename the temporary folder to the run folder (published)
   -> otherwise nothing is published

Around every stage: log duration and peak memory.
Memory check: use the thresholds and unknown-memory rule in D15.
Each run has its own run folder, so earlier runs are never overwritten (D28).
On any failure: clear error message with stage and row or file where applicable; no new result set is published and previous results stay untouched.
```

Rule: rows received = canonical customers + rejected rows + duplicate losing rows. Accepted rows = canonical customers + duplicate losing rows; rows received = accepted + rejected therefore also holds. Every input row has exactly one final destination; warnings may reference any destination and are not added to the row total. All five output files are published on every successful run, with headers for empty tabular outputs. Totals are checked in stage 4, before anything is published, and must reconcile, or the run is declared failed. Base volume for testing: 100,000 records; 10x is measured in a real run and 100x is attempted (D13).

## 3. Assumptions

These are guesses about the customer, to confirm with a real customer. They are not facts.

Terms used throughout: consent is the customer's agreement to the processing of personal data (GDPR); subscription is the customer's agreement to receive marketing, newsletter or information messages. They are separate states.

| # | Assumption | Status | Label |
| --- | --- | --- | --- |
| A1 | The customer is a supermarket chain with a loyalty program, physical stores plus web, app and social presence | Guess about the customer; first thing to confirm with a real customer | Assumed |
| A2 | The loyalty card is a stable key that every customer in the CRM has: exactly 16 digits, sometimes written with spaces in groups of 5, 9 and 2 digits. There is one card type only | Guess, based on cards checked by hand; to confirm | Assumed |
| A3 | Every row in the CRM export has at least one contact channel among email, phone and app installed (rule in D11), plus subscription state and consent state at export time. Last purchase date and last purchase amount are optional columns. Consent and subscription are separate states with a scope to confirm; the presence of a column alone does not make a profile eligible. A single consent value and a single subscription value are assumed to apply to all channels; whether they must be split per channel is confirmed with the customer, and the orchestrator rechecks it if needed | Guess about the customer | Assumed |
| A4 | The expected volume is 100,000 records per export | Guess; 10x is measured in a real run and 100x is attempted (D13) | Assumed |
| A5 | Consent values arrive in many spellings and are normalized to yes, no or unknown using the list in section 8 | Guess about the data | Assumed |
| A6 | Mapping score bands: above 90 safe, 60 to 90 with caution, below 60 no proposal. Every proposal stops the run until the analyst approves it; the band only tells the analyst how likely the mapping is right and never approves it automatically | Guess; values to confirm | Assumed |
| A7 | If more than 3% of profiles with a valid card have no contact channel, the report says the source probably broke. The value is configurable | Guess; 3% is a starting value, to confirm | Assumed |
| A8 | Creating a customer account requires a confirmed email or phone, so a profile with no contact channel should not exist | Guess about the customer; to confirm with a real customer | Assumed |
| A9 | The end user is a data analyst at the customer who prepares the marketing database | Guess about the customer; to confirm with a real customer | Assumed |
| A10 | Phone numbers can lose their leading 0 when a file is edited in Excel, so a nine-digit number starting with 7 is a Romanian mobile number without its 0; the default country prefix is +40 | Guess about the data; to confirm with the customer | Assumed |

## 4. Decisions

| # | Decision | Reason | Label |
| --- | --- | --- | --- |
| D1 | Build the scenario on a supermarket chain with a loyalty card | Easy to explain; the card is a stable key | Chosen |
| D2 | Outputs are designed for the data analyst who prepares the marketing database (A9) | Keeps the canonical table and the reports readable for the analyst | Chosen |
| D3 | Identity key (customer key) is the loyalty card number. After removing spaces and dashes it must be exactly 16 digits, kept as text so leading zeros survive; any other value is rejected with a clear reason (CARD\_EMPTY or CARD\_INVALID); control characters are removed first (D29); Excel scientific notation such as 1.23457E+15 is invalid. The same card written with or without spaces gives the same key. A row with an empty or invalid card is rejected, whatever consent or contact data it carries, and never enters the canonical table (a missing card column stops the run instead, D21) | Simple, testable; a wrong key cannot identify a customer | Chosen |
| D4 | Implement one source: the CRM customer-profile CSV. Profiles come from the CRM; where the CRM gets its data is outside this project | A campaign needs contact, consent and subscription state, which the CRM profile carries; time budget 8-10 hours | Chosen |
| D5 | Output is a canonical customer table, one row per winning customer, including normalized consent state, subscription state, contact fields, campaign eligibility and explicit ineligibility reasons. Optional first name, last name, last interaction timestamp, last purchase date and last purchase amount are kept when supplied (the last purchase amount is assumed to be the value of the last receipt, not the total spent; to confirm with the analyst); absent optional columns give empty values. Rejected rows and duplicate losing rows are separate outputs. Activity from other systems is a later extension via an orchestrator | Analyst needs it for segmentation | Chosen |
| D6 | A new or renamed column that gets a mapping proposal: the run stops, the proposal is written to a file, the analyst approves it and runs again; an approved mapping is saved in the synonym dictionary. The proposal is a JSON file in the output folder, completed by hand: each entry is approved, rejected (the column is then passed through unchanged with a warning, D27), or changed to another known field. Columns scoring below 60 are listed with no field so the analyst can assign one. A later orchestrator could read and answer the same file. A new column with no proposal is passed through (D27) | A wrong automatic mapping silently corrupts everything | Chosen |
| D7 | Mapping proposal comes with a match score from 0 to 100 | Easy for the analyst to read | Chosen |
| D8 | Use an AI agent only to propose mappings; no API key, so it is simulated with fixed answers plus a synonym dictionary | Easier to defend; no API access available | Chosen |
| D9 | For a profile with a valid card (D3), campaign eligibility at export time requires all three: consent = yes, subscription = active, and at least one valid contact channel (D11). The prototype does not check purpose or channel: it assumes a consent yes and an active subscription cover every channel and the intended purpose (A3). Consent no or unknown, or subscription inactive or unknown, makes the customer not eligible for campaigns. A structurally valid profile (read without cell-count or quoting errors, with a valid card) stays in the canonical table with both normalized states and all ineligibility reasons; unknown or missing states also produce a warning. Consent and subscription use separate value mappings (section 8). No consent history is inferred | The costliest error is contacting someone without valid consent or after they unsubscribed; valid data is kept for review | Chosen |
| D10 | Invalid optional field (for example a bad phone when a card exists, or a negative, zero or unreadable last purchase amount): field emptied, row accepted with a warning. A timestamp is invalid if it cannot be read, is outside the range that can be converted, or is later than the run time. Whether the customer is still reachable is decided by the contact rule in D11 | Do not lose a usable customer | Chosen |
| D11 | Contact rule: a customer needs at least one valid contact channel among email, phone and app installed. No single channel is mandatory, and a channel that is present but invalid counts as missing. For profiles with a valid card and no valid channel, the row is accepted with a strong warning, marked not eligible for campaigns, and counted separately. If their share passes the missing-contact threshold (A7), the report says the source probably broke | Under assumption A8 a profile with no contact channel should not exist; at volume it signals a broken source | Chosen |
| D12 | Write five files into a temporary folder: canonical customers, rejected rows, warnings, run summary and duplicates. After verification the folder is renamed to the run folder, so the files are published together or not at all. The canonical table is a contract for a later orchestrator: stable fixed columns (card\_number, first\_name, last\_name, email, phone, app\_installed, consent, subscription, last\_interaction\_at, last\_purchase\_at, last\_purchase\_amount, eligible\_for\_campaign, ineligibility\_reasons, source\_record\_number; pass-through columns follow them, D27), both normalized states, export-time campaign eligibility (yes or no) and reasons. The schema version is not a column: it is recorded in the run summary only. The summary includes the schema version, the export date (the modification date of the input file), the duration and peak memory of each stage, the total duration, all destination counts, warning counts, ineligibility counts, the effective thresholds and the observed percentages (numbers with the suffix \_pct), and a list of the mapping used for each input column (column, field, source: dictionary, approved or passed through) for traceability. Before sending, the orchestrator is expected to recheck current subscription, consent for the relevant purpose and scope, and channel availability; export-time eligibility is not a send authorization. The integration itself is not built | Export state can be stale by campaign time; a clean contract keeps the integration cheap later | Chosen |
| D13 | Test on 100,000 records; measure memory and time per stage (the four stages in section 2); a 1,000,000-record run (10x) is measured by hand and its figures go in the README; a 10,000,000-record run (100x) is attempted, and either its figures or a clean stop on the memory limit (D15) are documented, with an extrapolation as an estimate. The test file is synthetic data, generated once by a script written with AI assistance and reused to demonstrate the proof of concept; no real customer data is used | Matches the volume assumed in A4 | Chosen |
| D14 | Log duration and peak memory for each of the four stages in section 2; cheap measurement by default, detailed only with a debug flag. The run summary records the duration and peak memory of each stage, and the total run duration as a separate value | Detailed tracking slows the run | Chosen |
| D15 | Memory thresholds are a percentage of total memory: warning at 50%, clean stop at 80%; read per operating system; unknown total gives a warning and skips the check | Adapts to any computer | Chosen |
| D16 | All results are processed in memory at once; row by row is considered for 100x volume | Simple and fine at 100,000 records | Chosen |
| D17 | On failure: a clear operator message names the stage and the input row or output file where applicable; no new result set is published and previous results stay untouched. The temporary folder is deleted, so nothing that looks like a result is left behind and no personal data stays on disk; the log and the error message are kept outside it. With the debug flag the folder is kept and renamed failed\_YYYY-MM-DD\_HHMMSSZ. If the run folder name already exists, the run fails with a clear message and never overwrites it. A resume point is considered for large runs | A partial result looks like a good one and can be used by mistake | Chosen |
| D18 | Zero external dependencies | Runs immediately, nothing to install | Chosen |
| D19 | Customers who only have a physical card, with no contact and no consent, are outside this project and are treated as not contactable. Such customers are not expected in the CRM export; if one appears, D11 applies | Keeps the scope on the CRM profile | Chosen |
| D20 | Duplicates: among structurally valid rows (D9) sharing a card, the row with the most recent valid interaction timestamp wins. Consent and subscription both come only from that winning row, never combined across rows. Losing rows go to the duplicates file with card, source record number, timestamp and reason. A row with a valid timestamp beats a row with a missing or invalid one. If timestamps tie, or both are missing or invalid, the later input row wins, with a warning. If the timestamps cannot decide (either is missing or invalid, or they tie) and the two rows disagree on consent or subscription, the customer is marked not eligible with the reason conflicting duplicates, as the safe choice. Invalid timestamps, including future ones, are emptied under D10. Campaign eligibility is computed after the winner is chosen. Totals reconcile with the equation in section 2 | The latest state is the most trustworthy, and a newer withdrawal of consent must never be hidden by an older row; when the order cannot be known, the safe choice wins | Chosen |
| D21 | Whole-file problems stop or flag the run: an input file that does not exist or cannot be read, an empty file (zero bytes), a file with only a header, or a header followed only by blank rows is a clear error; a missing card column stops the run with a message; a missing consent or subscription column marks every canonical customer not eligible for campaigns, with an explicit reason and a strong run warning; two columns claiming the same field stop the run and ask the human; if more than 10% of rows are rejected, the report warns that the rejection rate is unusually high and the source is worth checking; the run does not stop, and the value is a configurable guess | An export that does not look as assumed in A3 is more likely a broken source than a real result | Chosen |
| D22 | Cleaning rules are written down: first and last names trimmed, inner whitespace collapsed, Unicode normalized to NFC, with Romanian cedilla variants of ș and ț converted to comma-below variants, preserving other diacritics and letter case; email trimmed and lowercased, valid only if it has no spaces, exactly one @ and at least one dot after it; phone normalized as described in section 8; dates read day first in a fixed list of formats (ISO 8601 such as 2026-11-04, DD.MM.YYYY and DD/MM/YYYY; MM/DD/YYYY is not accepted because it is ambiguous, so such a value is invalid under D10) and stored in ISO 8601; consent normalized to yes, no or unknown and subscription separately to active, inactive or unknown, and app installed to yes, no or unknown, using section 8. Unknown states never enable a campaign. A timestamp without a time zone is read in local time (D28). Missing optional name fields stay empty | Without written rules a reader cannot tell what cleaned means | Chosen |
| D23 | A row without a valid card cannot be matched to a customer: it is rejected and reported clearly, never guessed (D3). Smart matching of such rows is left out (section 6) | Consent and subscription cannot be attributed to a customer without a valid card; wrong-match risk, GDPR basis and time | Chosen |
| D24 | The AI agent receives only column names and up to 3 masked sample values per column (letters become x and digits become 9), never full rows. Values from the status lists in section 8 (such as yes, no, da, nu, active) carry no personal data and are not masked | Keeps personal data away from the agent | Chosen |
| D25 | If the agent fails, the system falls back to the synonym dictionary instead of stopping | The run must not depend on the agent | Chosen |
| D26 | Phone and email are stored for delivery by the orchestrator; this prototype sends nothing. A real deployment needs a privacy review. The rejected rows file keeps the original row, so it contains personal data, and the customer handles it under its own PII policy. Run files are created with restrictive permissions where the operating system allows it. Unknown columns passed through (D27) may carry special-category data such as religion or health, so the customer confirms they are allowed. No encryption or password protection is built, to keep zero dependencies (D18) | Limits the use of personal data to preparing the table | Chosen |
| D27 | Schema drift contract: known mandatory and optional fields are mapped and processed. A column with a header that is not recognized is passed through to the canonical table unchanged, after the fixed columns, and listed in the warnings; it never blocks the run. A column that gets a mapping proposal still waits for approval (D6) | Source columns are not lost when the format changes; the fixed columns stay the contract | Chosen |
| D28 | Each run writes into its own new run folder, named run\_YYYY-MM-DD\_HHMMSSZ in UTC, for example run\_2026-11-04\_163045Z. Files are first written into a temporary folder and renamed to the run folder only after verification. Earlier run folders are never overwritten | A failed or repeated run cannot mix files from different runs, and the analyst can compare runs. The date keeps the same time on another day apart, and the seconds keep two runs in the same minute apart. UTC keeps the name unique when the local clock goes back at the end of daylight saving time, when one local hour repeats; the summary keeps the local start time with its offset, and durations use a monotonic clock. A timestamp without a time zone is read in local time; one that falls in the repeated hour gets the warning TIMESTAMP\_AMBIGUOUS\_HOUR | Chosen |
| D29 | Read strictly with the standard Python CSV reader in strict mode; a custom reader is left out (section 6). Line endings LF, CRLF and CR are accepted. A row with more cells than the header, in a file that still parses, is rejected alone with the reason EXTRA\_CELLS only when an extra cell holds a value: it is kept in full in the rejected rows file and the run continues. If all extra cells are empty, the row is kept with the warning TRAILING\_EMPTY\_CELLS. A row with fewer cells than the header is not rejected: the cells that are present are kept, missing cells are treated as empty and the row gets the warning SHORT\_ROW (a short row can also mean shifted cells), and each field follows its own rule (an empty optional or pass-through cell stays empty and never rejects the row; a missing card rejects the row under D3; a missing consent or subscription is unknown under D9). Text after a closing quote rejects that row alone with the reason BAD\_QUOTING. A record that spans more than one physical line gets the warning MULTILINE\_RECORD, because a quote closed by accident further down can merge rows; a record that spans more than 5 physical lines stops the whole run with UNCLOSED\_QUOTE, naming the line where it started (the limit is fixed in code). An unclosed quote, which can swallow the rows that follow, stops the whole run the same way and no new result set is published. A quote in the middle of an unquoted field is not detected by the standard reader and passes as text: this is a known limitation, documented. A file that is not valid UTF-8 stops the whole run with a clear message, and invalid characters are never replaced automatically. A BOM at the start of the input is accepted and ignored. A control character is any Unicode control character (category Cc) other than tab, line feed and carriage return, which count as whitespace. Control characters are removed from every field value, from the column names in the header and from the original row kept in the rejected rows file, before the field's own rule is applied, and the rest of the value follows that rule as if they had not been there; if any was removed, the row gets the warning CONTROL\_CHARACTER\_REMOVED, which names the field. Nothing else is changed or guessed. A valid multiline field still passes | Silent loss of data is worse than a rejected row or a stopped run. Cost: one cell-count check per row, expected to be small and measured in the 100,000-record test (D13). The real price is that one unclosed quote stops the whole run, and a stray quote inside an unquoted field is not caught | Chosen |
| D30 | Output formats: canonical customers, rejected rows, warnings and duplicates are CSV files in UTF-8 without a BOM; the run summary is a JSON file. Each rejected input row is one line, with all its errors in one column. Rows are identified by source\_record\_number, the position of the record in the file, not a line number, since a quoted field can span lines. An Excel (XLSX) export is left out | CSV and JSON need no dependency (D18); a hand-built XLSX writer would use time that is better spent on reading and reporting | Chosen |

## 5. Labels used in the spec

The customer is hypothetical. Each statement in the spec carries one of three labels:

- **Given**: stated in the assignment brief.
- **Assumed**: a guess about the customer, with a note on what to confirm with a real customer.
- **Chosen**: a decision made, with the reason and what was given up.

## 6. Considered and left out (with reason)

- Other sources feeding the CRM or sitting beside it (stores, app, online, social, logs): the profile comes from the CRM, so where the CRM collects its data is outside this project; interface kept compatible.
- API and log sources: considered; a batch CSV was chosen to fit the 8-10 hour budget. A pipeline connection through an API and an export into the orchestrator can be added later.
- Excel (XLSX) export: left out; CSV opens in Excel, and a hand-built writer would use time that is better spent on reading and reporting (D30).
- Customers with only a physical card and no contact or consent: outside this project, treated as not contactable.
- Smart matching of people without a card by phone, name or email: risk of wrong matches, needs a GDPR basis and consent, needs more time.
- Real pop-up or notification for mapping approval: replaced by a JSON file the analyst completes by hand; a later orchestrator could read and answer the same file.
- Live AI model: no API access; simulated.
- Consent history (given, withdrawn, given again): the export carries only the state now.
- Final pre-send recheck of subscription and consent: belongs to the later orchestrator. This project checks both states at export time and prepares the contract; it does not send messages.
- Row-by-row processing and a resume point: considered for 100x volume, not needed at 100,000 records.
- Database, authentication, streaming: not required by the brief.
- A custom CSV reader that rejects a quote in the middle of an unquoted field: estimated 1 to 2 hours; the standard reader in strict mode is used and the limitation is documented (D29).
- An `--export-date` argument: left out; the export date is the modification date of the input file.
- A `card_as_read` column in the rejected rows file: left out; the original row already holds the value.
- Encryption or password protection of output files: left out; it needs an external dependency (D18), and the orchestrator and the analyst must be able to read the files. Protection is by file permissions and the customer's PII policy (D26).

## 7. Engineering rules and the tests that prove them

1. No row disappears silently; every row gets an outcome.
2. Every failure produces an operator message, not a traceback.
3. A run produces a full set of files or nothing.
4. Every decision records the reason and what was given up.
5. Brainstorming, specification, plan and implementation all live in the repo, each in its own folder.
6. One README, verified from a clean checkout.
7. AI use is visible in the repo: CLAUDE.md or AGENTS.md, the spec and the plan.
8. An AI log in the repo records, for each task, what was asked, what the AI proposed, what was rejected or corrected, and how the result was verified.
9. Test expectations are derived from the specification before the code exists, and each is checked against a case worked out by hand.

Test cases that prove the rules above. Each is a regression test with a fixed expected result. Every case is implemented as an automated test and run before the work is declared done; a case without a passing test counts as unfinished. Related cases may share one parametrized test. The cases are implemented after the synthetic sample files are generated.

| Case | Expected result |
| --- | --- |
| A row has more cells than the header (stray separator) | Only that row is rejected, kept in full in the rejected rows file with the reason EXTRA\_CELLS and its source record number; the run continues; total still reconciles; an extra column with a header and an unknown name is passed through unchanged and reported with a warning, not rejected |
| A quoted field is never closed and swallows the next row | Run stops with an error naming the line where the quote opened; no new result set is published; a valid multiline field still passes |
| Input is not valid UTF-8 | Run stops with a clear message naming the required encoding; invalid characters are not replaced; no traceback |
| Output folder cannot be written | Clear operator message; no partial result files |
| Timestamp is invalid: unreadable, out of range (year 0001), or later than the run time | Field emptied with a warning; the profile is kept; the run does not crash |
| A text value contains a control character | The control character is removed in every field (name, card, email, phone, consent, subscription, app installed, pass-through column) and the rest of the value follows the field's own rule; the row gets the warning CONTROL\_CHARACTER\_REMOVED naming the field; the written files stay valid |
| Rejected rows have different numbers of errors | Every rejected row is one line with the same columns; all its errors are listed in one column |
| Failure after some files were written | Nothing is published, previous results stay untouched, and a clear message names the stage and the file that failed |
| Run is repeated on the same input | Same outputs, same totals |
| Memory passes 50% and then 80% of total | Warning first, then a clean stop with a message; unknown total memory gives a warning and skips the check |
| Timestamp 0001-01-01T00:00:00+01:00 (underflow when converted to UTC) | Field emptied with a warning; the profile is kept; no crash |
| Same card twice, older row eligible, newer row withdraws consent or deactivates subscription | Newer row wins; both states come from it; customer is not eligible for campaigns; older row is in the duplicates file; totals reconcile |
| Same card twice with the same timestamp, or both timestamps missing or invalid | Later row in the file wins, with a warning; totals reconcile |
| Empty file (zero bytes) | Clear error; no result files |
| Card column missing or not recognized after mapping | Run stops with a clear message; no result files |
| Consent or subscription column missing | Every canonical customer marked not eligible for campaigns, with a reason naming the missing state and a strong run warning; all five outputs are still published |
| Two columns map to the same field | Run stops and asks the human to choose; nothing is guessed |
| Most rows are rejected | Above the rejection threshold in D21, the report warns that the rejection rate is unusually high and the source is worth checking; the run is not stopped |
| First name and last name each written once with cedilla variants and once with comma-below variants | After cleaning, both give the identical value |
| Each consent value in the lists, in different letter cases and spacings; and a value not in the lists, including an empty field and "nu accept" | Listed values map to yes or no as defined; an unknown value makes the customer not eligible for campaigns, with a warning |
| All nine consent and subscription combinations, with a valid card and a valid contact channel | For consent yes, no, unknown crossed with subscription active, inactive, unknown, only yes plus active is eligible. All nine profiles stay canonical; both states and all reasons are kept. Unknown states produce warnings |
| Consent yes and subscription active, but no valid contact channel | Profile stays canonical, not eligible, with a strong warning under D11; it counts toward the missing-contact threshold |
| Each listed subscription value in mixed case and with surrounding spaces; empty and unrecognized values | Values map exactly as in section 8; inactive and unknown are not eligible; unknown produces a warning. Consent is normalized separately |
| Optional first name or last name absent or empty | Profile is kept with empty optional names; no rejection solely for a missing name |
| Successful run with no rejected rows, warnings or duplicates | All five output files exist; empty tabular outputs keep their headers; the run summary reconciles counts and records the effective thresholds |
| Input contains a canonical winner, a duplicate losing row and a rejected row | Input count equals canonical count plus duplicate losing count plus rejected count. Warnings do not count as extra rows |
| Output contract of a successful run | The run summary carries the schema version and the export date (the modification date of the input file); the canonical table has no schema version column and labels eligibility as eligibility at export time; the prototype sends no message |
| A row whose card is too short, contains letters, or is empty (for example 1234 5678 or 12345678901234AB) | Row is rejected with a reason that names the card; it does not enter the canonical table and no eligibility is computed; it counts as a rejected row and totals reconcile |
| The same card written once with spaces in groups of 5, 9 and 2 digits and once without spaces | Both give the same key; the second appearance is handled as a duplicate under D20; totals reconcile |
| Same card twice with the same consent and subscription, older row with a real timestamp, newer row with a timestamp in the future | The future timestamp is invalid and is emptied with a warning; the row with the real timestamp wins; totals reconcile |
| Input file does not exist | Clear error naming the path; no result files; no traceback |
| Input file exists but cannot be read (for example no permission) | Clear error naming the file and the reason; no result files; no traceback |
| Header only, or a header followed only by blank rows | Clear error saying there are no data rows; no result files |
| A column with a header and an unknown name, with no mapping proposal | Passed through to the canonical table unchanged, after the fixed columns, and listed in the warnings; the run continues |
| A new column that gets a mapping proposal | The run stops and writes a mapping proposal file; after the analyst approves it and runs again, the column is mapped and the approved mapping is saved in the dictionary |
| Two runs, one after the other | Each writes its own run folder; the first run folder is left untouched |
| Same card twice, one timestamp missing or invalid, and the two rows disagree on consent | The customer is not eligible, with the reason conflicting duplicates and a warning; the losing row is in the duplicates file; totals reconcile |
| Same card twice with the same timestamp, and the two rows disagree on subscription | The customer is not eligible, with the reason conflicting duplicates and a warning; the later row in the file is the kept row; totals reconcile |
| Same card twice, one timestamp missing or invalid, and the two rows agree on consent and subscription | The row with the valid timestamp wins; no conflict reason; a warning for the invalid timestamp; totals reconcile |
| Output CSV files written, with a name that contains ș and ț | Each CSV output is UTF-8 without a BOM; the name reads back identical |
| Phone written as 0722123456, 722123456, 0040722123456, +40722123456 and 12345 | The first four give the same +40722123456, and the nine-digit form adds a warning; the short number is emptied with a warning |
| An input file that starts with a BOM | Read normally; the first column name has no hidden character |
| A row has fewer cells than the header | Row is not rejected; present cells are kept and missing cells are empty; a warning says the row is shorter than the header; a missing card rejects the row under D3; a missing consent or subscription is unknown, so the profile is not eligible; totals reconcile |
| Optional or pass-through cells are empty in some rows and filled in others | Filled values are kept unchanged, empty cells stay empty, and no row is rejected for that reason |
| The first line of the file does not look like a header (for example it holds a card number) | Run stops with the message that the first line does not look like a header; no result files |
| File with semicolon delimiters, and a file with tab delimiters | The semicolon file is read exactly like the comma file; the tab file stops the run with a clear message naming the accepted delimiters |
| More than 3% of profiles with a valid card have no contact channel, and a second file with exactly 3% or less | Above 3%: the report says the source probably broke; at or below 3%: only the per-row strong warnings; both counts appear in the run summary |
| The simulated agent fails during mapping | The run falls back to the synonym dictionary and does not stop; the fallback is written in the log |
| What the agent receives | Only column names and masked sample values; no complete row, no unmasked email, phone or card |
| Mapping proposals with scores above 90, from 60 to 90 and below 60 | Above 90 and 60 to 90: the run stops and waits for approval, with the band shown to the analyst; below 60: no proposal, the column is listed with no field in the proposal file and is passed through with a warning; no proposal is ever approved automatically |
| Run summary of a successful run | Contains, for each of the four stages, its duration and peak memory, and the total duration as a separate value |
| An unexpected internal error in a stage | Clear operator message naming the stage; no traceback; nothing published |
| A run fails after files were written | The temporary folder is deleted and the log and error message remain; with the debug flag the folder is kept as failed\_YYYY-MM-DD\_HHMMSSZ |
| The run folder name already exists | The run fails with a clear message and the existing folder is untouched |
| Run files on a system with POSIX permissions | Run folder and files are readable only by their owner; on a system without POSIX permissions the check is skipped and the skip is logged |
| Dates written as 2026-11-04, 04.11.2026, 04/11/2026, 11/13/2026 and 13.13.2026 | The first three give the same stored value; the last two are invalid, emptied with a warning, and the profile is kept |
| Emails with surrounding spaces and capital letters, with a space inside, with two @, and with no dot after the @ | The first is trimmed and lowercased; the others are emptied with a warning |
| A quoted field that closes correctly after 2 to 5 physical lines | Row kept; warning MULTILINE_RECORD; totals reconcile |
| A quote closed by accident further down, merging rows over 15 lines | Run stops with UNCLOSED_QUOTE naming the line where the record started; no result files |
| Text right after a closing quote (for example "abc"def) | That row alone is rejected with BAD_QUOTING; the run continues; totals reconcile |
| A row with extra cells that are all empty, and a row with a value in an extra cell | The first is kept with the warning TRAILING_EMPTY_CELLS; the second is rejected with EXTRA_CELLS |
| A quote in the middle of an unquoted field (for example ab"c) | Read as text without an error; this is the documented known limitation |
| The same file with LF, CRLF and CR line endings | Identical results |
| Card written as 1.23457E+15; a valid 16-digit card with a control character inside; a 15-digit card with a control character inside | The first is rejected as CARD_INVALID; the second is kept as a valid card with the warning CONTROL_CHARACTER_REMOVED; the third is rejected as CARD_INVALID |
| A name with extra inner spaces and a decomposed accent | Trimmed, inner whitespace collapsed, stored in NFC |
| Name Gheorghe followed by the control character U+0001 | Stored as Gheorghe with the warning CONTROL_CHARACTER_REMOVED; the row is kept |
| Export date | The summary export date equals the modification date of the input file |
| Mapping decisions: approve, reject, change to a known field, change to an unknown field | Approved and changed mappings are saved in the dictionary; a rejected mapping is passed through unchanged with the warning UNKNOWN_COLUMN (D27); a change to an unknown field is a usage error with a clear message |
| Masked sample values | Letters become x and digits become 9; status values such as da, nu, yes, active stay unmasked; at most 3 samples per column |
| Run folder name | Ends with Z and is in UTC; two runs one hour apart across the daylight saving change get different names |
| A timestamp without a time zone that falls in the repeated hour | Read in local time with the warning TIMESTAMP_AMBIGUOUS_HOUR |
| Run summary mapping list | Each input column appears with its field and a source of dictionary, approved or passed through |
| Last purchase amount written as 12.50, 12,50, -12.50, 0, 12 lei, 1,234 and abc | 12.50 and 12,50 give 12.50; -12.50, 0, 12 lei, 1,234 and abc are emptied with PURCHASE_AMOUNT_INVALID and the profile is kept |

## 8. To confirm with a real customer

- Exact column list for the CRM CSV: a proposal exists, not confirmed. Card number: 16 digits after removing spaces and dashes; any other length is rejected (D3). Consent state (needed for eligibility; if the column is missing, every customer is not eligible for campaigns). Subscription state (needed for eligibility, same rule; normalization and missing-value rules below). Contact channels email, phone and app installed (at least one valid, see D11). Last interaction timestamp, last purchase date, last purchase amount (assumed to be the value of the last receipt, read as a plain number; the amount and its currency are to be confirmed with the analyst, since customers may not all be in Romania), first name and last name (all optional). Names are personal data (see D26) and are cleaned like other text values.
- Consent values, proposed list. Read as yes: da, yes, y, true, 1, accept, acept, accepted, opt-in, optin, ok. Read as no: nu, no, n, false, 0, refuz, refuzat, refused, opt-out, optout, retras, withdrawn, revoked, nu doresc. Matching ignores spaces at the ends, letter case, and hyphens, spaces and dots between letters, and compares the whole value, so "nu accept" is unknown, not yes. Anything else, including an empty field, is unknown: the customer is not eligible for campaigns, with a warning (D9). These mappings apply only to consent and must not be reused automatically for subscription. The value ok is ambiguous, since a CRM may use it as a technical status; to verify with a real customer.
- Subscription values, proposed list. Active: active, activ, subscribed, yes, da, y, true, 1. Inactive: inactive, inactiv, unsubscribed, no, nu, n, false, 0. Matching trims surrounding whitespace, ignores letter case and compares the whole value. An empty or unrecognized value is unknown. A missing subscription column makes every canonical customer not eligible for campaigns, with a strong run warning. Inactive or unknown subscription does not reject a structurally valid profile (D9): it stays in the canonical table, marked not eligible with the reason; unknown also produces a warning. The source meanings, scope and mappings are confirmed with the customer before use.
- App installed values, proposed list. Yes: yes, da, y, true, 1, installed. No: no, nu, n, false, 0. Matching trims surrounding whitespace, ignores letter case and compares the whole value. An empty or unrecognized value is unknown and counts as no valid app channel (D11).
- Phone normalization, proposed. Keep digits and a leading plus sign. A 0040 or +40 prefix becomes +40; a number starting with a single 0 becomes +40 followed by the rest; a nine-digit number starting with 7 is read as a Romanian mobile number whose leading 0 was lost when the file was edited in Excel, and becomes +40 followed by the number, with a warning; a number with another country prefix is kept as given; fewer than 8 or more than 15 digits is invalid and emptied with a warning (D10). The default prefix +40 and the lost leading 0 are assumptions (A10) to confirm with the customer.
- Consent and subscription are separate input states. Consent is the agreement to the processing of data under GDPR (opt-in belongs here); subscription is the agreement to receive marketing, newsletter or information messages. Valid consent means yes for the intended processing purpose, and subscription means active for the intended communication scope. A generic consent flag must not be assumed to cover all purposes or channels. GDPR is the legal framework, not a separate yes or no field. The meaning and scope of both states are confirmed with the customer; this draft does not establish legal permission.
- Header synonyms proposed for the first dictionary (compared after normalization, whole name): last\_name also "nume familie"; phone also "tel", "tel.", "mobil" and combinations such as "tel mobil" and "tel. mobil"; app\_installed also "aplicatie" and "app"; consent also "acord gdpr" and "gdpr"; subscription also "newsletter", "notificari", "promotii", "marketing" and "campanii marketing"; last\_purchase\_amount also "valoare bon" and "total bon". Words that mix both meanings are ambiguous: opt\_in is proposed as consent and marketing\_consent as subscription; to confirm with the customer.
- Whether consent and subscription are kept per channel in the real CRM, which would split eligibility by channel.
- Out of contract, proposed. A file with no header (the first line does not look like a header) stops the run with that message. Comma and semicolon delimiters are accepted, detected from the header line; any other delimiter stops the run. A column that keeps its name but changes its meaning cannot be detected, so it is out of contract and is confirmed with the customer. Merged or split columns (for example one name column instead of first and last name) are out of contract: the new columns are passed through unchanged (D27) with a warning, and the fixed fields stay empty.
- Whether the customer wants stronger protection for the rejected rows file than permissions and its own PII policy, and whether unknown columns that may carry special-category data are allowed (D26).
