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
