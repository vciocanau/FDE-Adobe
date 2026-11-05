# AI log

Record of the points where the AI proposed something and the owner rejected or changed it. Updated at each stage (brainstorming, specification, plan, implementation).

| #  | Topic | AI proposed | Owner decided | Why | Spec |
| -- | ----- | ----------- | ------------- | --- | ---- |
| 1  | Mapping agent | Rules and a synonym dictionary first; the agent as a later extension | Agent included from the start, simulated because there is no API key | Defensible use of AI where it helps; a human approves every mapping | D8, D24, D25 |
| 2  | Card format | An interval of 10 to 16 digits | Exactly 16 digits, one card type | One chain has one card type | A2, D3 |
| 3  | Missing-contact threshold | 5% as a starting value | 3% | 3,000 profiles out of 100,000 is already a large number | A7, D11 |
| 4  | Rejection-rate warning | Strong wording ("source probably broke") also at 10% rejected rows | Cautious wording at 10%: the rate is unusually high and the source is worth checking; the strong wording stays only for the 3% missing-contact case | Many rejected rows do not mean a broken source; a profile with no contact should not exist at all (A8) | D11, D21 |
| 5  | Matching across sources | Wording that said matching the same person across sources was left out | Identity is the card number; only rows without a card are left unmatched | The AI wording was wrong: matching by card is already done | D3, D23 |
| 6  | Consent value "ok" | Warned that it is ambiguous | Kept in the list, marked to verify with a real customer | Owner decision; the risk is written in the spec | Section 8 |
| 7  | Duplicates | Offered first row, last row or reject both | The most recent interaction timestamp wins; losing rows go to a duplicates file | The latest state is the most trustworthy | D20 |
| 8  | Memory thresholds | A fixed value in MB, configurable | A percentage of total memory: warning at 50%, clean stop at 80% | Adapts to any computer | D15 |
| 9  | Consent granularity | Offered consent kept per channel | One value assumed for all channels; the orchestrator rechecks it | Keeps the first version small; per channel is recorded as a point to confirm | A3, D9, section 8 |
| 10 | Rows without a card | Left open whether such a row enters the canonical table | Rejected, never in the canonical table | Consent cannot be attributed to a customer without a card | D3, D23 |
| 11 | Output encoding | UTF-8 with a BOM so that Excel shows ș and ț correctly | UTF-8 without a BOM; a BOM on input is accepted | The files are read by the orchestrator, and a BOM can corrupt the first column name | D29, D30 |
| 12 | Label for the key | The bare word "identity" | "Identity key (customer key)" | The bare word is ambiguous for a reader outside the discussion | D3 |
| 13 | Phone numbers, lost zero | Digits plus one standard prefix | Also assume Excel drops a leading 0: a nine-digit number starting with 7 is a Romanian mobile number; confirm with the customer | A real cause of bad numbers that the AI had not considered | A10, section 8 |
| 14 | Working method | Ran ahead with setup and applied some edits before approval | Analysis first; explicit consent for each change | Avoids unrequested changes | Process |
| 15 | Rows shorter than the header | Treat like rows with extra cells: reject the row | Not rejected: present cells are kept, missing cells are empty, a warning is recorded (the AI added the warning, accepted by the owner) | Optional and unknown columns may legitimately be empty; rejecting would lose usable profiles | D29 |
| 16 | Temporary folder after a failure | Offered mark-and-keep or delete | Delete by default, keep as failed_YYYY-MM-DD_HHMMSS only under the debug flag | Same logic as D17: nothing that looks like a result is left behind, and no personal data stays on disk | D17 |
| 17 | Card in the rejected rows file | Offered a `card_as_read` column | Not added | The original row already holds the value | Spec section 8 |
| 18 | Export date | Offered an optional `--export-date` argument | Not added; the export date is the modification date of the input file | Keeps the command line small | Spec sections 3, 8 |
| 19 | Time zone of the run folder name | Local time of the machine (the AI missed the end of daylight saving time, when one hour repeats) | UTC with a Z at the end; durations measured with a monotonic clock; timestamps without a zone read in local time with a warning | Two runs an hour apart could get the same name, and durations could come out wrong | Spec sections 6, 8; D28 |
| 20 | Name of the record number | `source_row` | `source_record_number` (the owner pointed out that a row is not a record; the AI chose the full words) | A quoted field can span lines, so the number is not a line number | Spec section 8 |
| 21 | CSV reader | A reader of our own, to reject a quote in the middle of an unquoted field (estimated 1 to 2 hours) | The standard Python reader in strict mode; the stray-quote risk is documented as a known limitation | Time budget; the standard reader still rejects text after a closing quote and stops on an unclosed quote | Spec section 4 |
| 22 | Name with a control character | Empty the name with a warning (as D29 says for optional names); the AI repeated this in an example without noting that it loses a correct name | Remove only the control character, keep the rest of the name, write the warning | Same principle as pass-through columns: nothing is invented, only the stray character is removed | Spec section 6; D29 |
| 23 | Control characters in other fields | Left the older rule in place for phone, email, card, consent, subscription and app installed (empty or reject the field), after name had changed to removal | One rule for every field: remove the control character, keep the rest, follow the field's own rule, warn with one code `CONTROL_CHARACTER_REMOVED` | The owner noticed the inconsistency; same principle as names: nothing is guessed, only the stray character is removed | Spec sections 6.1 to 6.5, 9; D29 |
| 24 | Last purchase amount rules | Negative amount invalid (as in D10); open questions about zero and thousands separators | Zero invalid, negative amount invalid (the owner first considered a negative amount as a possible return, then decided not to accept it), thousands separators not accepted, currency not read and to be confirmed with the analyst because customers may not all be in Romania | Keeps the rule simple and avoids guessing ambiguous values | Spec section 6.10; D10 |
| 25 | 10x and 100x volume | Extrapolate 10x and 100x from the 100,000-record test (D13) | Measure a real 1,000,000-record run and write the figures in the README; attempt a 10,000,000-record run and document whether it completes or stops on the memory limit | Real figures are stronger than an estimate, and a clean memory stop proves D15 | Spec section 11.7; D13 |

## Corrections found during implementation

Errors in AI-produced work that the tests or the measurements caught, and how each was corrected.

| # | What the AI produced | How it was found | Correction |
| -- | -------------------- | ---------------- | ---------- |
| 1 | Starting dictionary without the canonical names `last_interaction_at` and `last_purchase_at`, so a file using the canonical names stopped for a mapping approval | Failing end-to-end test (`test_success`) | Every canonical field name maps to itself; regression test added |
| 2 | A test card written as 5-9-2 digit groups that was not the same card | The duplicate test failed on correct code | Test data corrected; code unchanged |
| 3 | Control-character removal character by character: 7 s of cleaning for 100,000 records | Profiling the volume test | Regular expression over U+0000–001F and U+007F–009F, checked equal to Unicode category Cc; cleaning time down to about 4 s |
| 4 | A memory guard that the specification says stops a run cleanly at 80% | The 10,000,000-record run was killed by the operating system before the first check | Reported to the owner as a limitation; decision recorded below |
| 5 | An input column named like an output column (`eligible_for_campaign`) overwrote the computed eligibility, so a customer without consent could be published as eligible | Independent review of the finished branch | Pass-through columns get unique names that never collide with output columns; regression test |
| 6 | Suffixes for repeated unknown column names could collide and lose a value | Independent review | Suffixes skip every name already used; regression test |
| 7 | After text following a closing quote, the standard reader dropped the rest of the line, so a quoted field opened there became fake customer rows | Independent review | The rejected record ends where its quotes balance again; reading resumes after it; regression test |
| 8 | A malformed time-zone offset (`+24:00`) stopped the whole run | Independent review | Offsets limited to 00:00–23:59; the field is emptied with `TIMESTAMP_UNREADABLE`; regression test |
| 9 | An approved mapping was saved in the dictionary before the conflict check | Independent review | Approved mappings are saved only after the whole header maps without a conflict; regression test |
| 10 | A traceback when the log folder could not be created; column names (possibly personal data) in the log | Independent review | One operator line with `OUTPUT_NOT_WRITABLE`; the log names column positions; regression tests |
| 11 | Several acceptance cases proven only in part | Independent review | Tests extended for AC-11, AC-25, AC-37, AC-38, AC-42, AC-51, AC-63, AC-66 |

| 12 | A memory-per-input ratio of 35, computed with the file size in decimal MB | Re-measurement asked by the owner, with sizes in MiB: 39 at 1x, 29 at 10x | Ratio set to 40; runs recorded in `docs/performance-log.md` |

## Memory guard at 100x

The AI offered two options: a memory estimate before reading, or documentation only. The owner chose the estimate and asked for the 1x, 10x and 100x runs to be repeated and logged to validate it. It was added as the OpenSpec change `add-preflight-memory-check`. The 100x run now stops cleanly with `MEMORY_LIMIT` before reading.
