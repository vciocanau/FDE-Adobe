# Proposal

## Why

The 10,000,000-record run (100x) was repeated on a desktop with 16 GB of RAM (Windows, Python 3.14) with the memory estimate and the stop disabled, to see where the run fails. Physical memory reached 100% and Windows moved memory to disk; after 176 seconds in the read stage Python raised `MemoryError`. The run ended cleanly, without a traceback and without publishing anything, but with `INTERNAL_ERROR` (exit 5), the code for an unexpected failure. Running out of memory is an expected failure with its own code, `MEMORY_LIMIT` (exit 4), so the operator was told the wrong cause.

## What Changes

- When the system refuses memory during a run (`MemoryError`) before a memory check could stop it, the run stops with `MEMORY_LIMIT` and exit code 4, with the message `Memory ran out in stage <name>; run stopped`. Nothing is published, as for any other stop.
- The same desktop runs showed that the process peak was never read on Windows: every stage logged `peak memory None MB`, so the warning and stop thresholds (spec 10.3) never applied there. The Windows call passed the process handle as a 32-bit integer on 64-bit Windows and failed. The call now declares its argument types. This fixes existing behavior (spec 10.3 step 6) and needs no specification change; the existing Windows-only test proves it on a Windows machine.
- The specification's code table and section 10.3 gain this case; a new acceptance case, AC-69, proves it.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `ingestion`: adds a requirement for memory that runs out during a run.

## Impact

- `ingest/cli.py` (one more handled error), `ingest/ops.py` (Windows peak reading), `tests/test_cli.py` (one test).
- Specification sections 9, 10.3 and 11, brainstorming D15, the OpenSpec main spec, `docs/performance-log.md` and the README.
- No new dependency; no change to runs that do not run out of memory.
