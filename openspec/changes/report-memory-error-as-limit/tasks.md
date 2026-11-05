# Tasks

## 1. Error handling

- [x] 1.1 Add a CLI test for AC-69: `ingest.rows.process` raises `MemoryError`; verify exit 4, `ERROR MEMORY_LIMIT [stage clean]`, no traceback, no run folder. Verify it fails before the code change.
- [x] 1.2 Handle `MemoryError` in `ingest/cli.py` before the generic handler; verify the AC-69 test and the full suite pass.

- [ ] 1.3 Declare the argument and return types of `GetCurrentProcess` and `GetProcessMemoryInfo` in `ingest/ops.py`; verify on the Windows desktop that `tests/test_ops.py` (`test_windows_memory`) passes and that stage lines show a peak instead of `None`.

## 2. Documents and measurements

- [ ] 2.1 Add the case to specification sections 9, 10.3 and 11 (AC-69), brainstorming D15, the OpenSpec main spec (sync) and the README.
- [ ] 2.2 Record the desktop runs (1x, 10x, 100x with the estimate, and 100x with the estimate and the stop disabled) in `docs/performance-log.md`.
