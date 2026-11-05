# Proposal

## Why

A 10,000,000-record run (100x) was killed by the operating system after 19 seconds, before the memory guard's first check at record 10,000. The whole file is loaded before that check, so the specification's promise of a clean stop at the memory threshold (spec 10.3) did not hold for large files.

## What Changes

- Before the input is read, the run estimates its peak memory from the size of the input file: 40 MB of memory for each MB of input, rounded up from the ratios measured at 1x (39) and 10x (29).
- If the estimate is above `--memory-stop` (default 80%) of total memory, the run stops at once with `MEMORY_LIMIT`, exit code 4, before reading the file. The message gives the file size, the estimate and the limit.
- If total memory cannot be read, the estimate is skipped, as the other memory checks are (`MEMORY_TOTAL_UNKNOWN`).
- The estimate is recorded in the log, and the measured ratio is logged again for each test run (1x, 10x, 100x) in `docs/performance-log.md`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `ingestion`: adds a requirement for the memory estimate before reading.

## Impact

- `ingest/ops.py` (estimate), `ingest/cli.py` (call before reading), tests.
- Specification section 10.3 and brainstorming D15 gain one sentence each; README performance section updated.
- No new dependency; no change to outputs of runs that fit in memory.
