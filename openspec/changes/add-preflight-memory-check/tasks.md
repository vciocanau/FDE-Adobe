# Tasks

## 1. Estimate and stop

- [x] 1.1 Add `estimate_peak_mb(input_mb: float) -> float` (40 MB per MB) and `MemoryGuard.preflight(input_mb)` in `ingest/ops.py`; verify with unit tests for the three scenarios of the delta spec (200 MB stops, 100 MB passes, unknown total skips).
- [x] 1.2 Call the pre-flight check in `ingest/cli.py` before `read_file`; verify with a CLI test that a stop happens with exit 4, no run folder, and that the input file was never opened (patched `read_file` not called).
- [x] 1.3 Log the estimate and the measured ratio (peak MB / input MB) at the end of each run; verify the log line exists in a CLI test.

## 2. Documents and measurements

- [x] 2.1 Add the rule to specification section 10.3, brainstorming D15, the OpenSpec main spec (sync) and the README; verify `openspec validate --specs` passes.
- [x] 2.2 Run 1x, 10x and 100x synthetic files and record size, durations, peak memory, ratio and outcome in `docs/performance-log.md`; verify the 100x run ends with exit 4 and `MEMORY_LIMIT` before reading.
