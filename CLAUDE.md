# Instructions for AI agents

This repository is spec-driven. Read in this order before changing anything:

1. `docs/specification/specification.md`: the contract, the authority. `openspec/specs/ingestion/spec.md` mirrors it in OpenSpec form.
2. `docs/brainstorming/brainstorming.md`: why each rule exists (assumptions A1–A10, decisions D1–D30).
3. `docs/plan/2026-11-05-ingest-plan.md`: how the code is organized and which task built what.

## Rules

- Python 3.11+, standard library only (D18). No new dependency; `tzdata` is optional on Windows only.
- Run the tests with `python -m unittest -v`; the 100,000-record test with `INGEST_VOLUME=1`.
- Test first. Every test's docstring names the acceptance case (AC-xx) or spec section it proves; expectations come from the specification, not from the code.
- Every code (run error, rejection, duplicate reason, warning) is a name from specification section 9. A new code is added there first.
- No traceback reaches the operator; every stop prints `ERROR <CODE> [stage <name>] <message>`.
- No personal value (card, name, email, phone) in the log.
- Documents are in English and impersonal. Every proposal that the owner rejects or changes is recorded in `docs/ai-log.md`.
- A change of behavior starts as a change to the specification (an OpenSpec change proposal), then the tests, then the code.
