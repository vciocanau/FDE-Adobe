# Design

## Context

The memory estimate before reading stops a file that clearly cannot fit. A file that passes the estimate, or a run with the stop share raised, can still exhaust memory. The checks every 10,000 records only see the peak after a stage has allocated it; a single large allocation (loading the whole file) can fail inside the allocation, before any check runs. Python then raises `MemoryError`, which reached the generic handler and was reported as `INTERNAL_ERROR`.

## Goals / Non-Goals

**Goals:** the operator gets the right code and exit (`MEMORY_LIMIT`, 4) whenever the run fails for lack of memory; nothing is published.

**Non-Goals:** recovering or continuing after the error; streaming the read and clean stages (D16 stays).

## Decisions

- **Reuse `MEMORY_LIMIT` instead of adding a new code.** The operator's action is the same (smaller file, larger machine, or streaming), and scripts that react to exit 4 keep working. A separate message, `Memory ran out in stage <name>; run stopped`, distinguishes it from the threshold stop in the log.
- **Handled in the command line next to the other stop handlers**, so the stage name, the clean-up of the temporary folder and the log follow the existing failure path (D17). By the time the handler runs, the stage's objects are released, so writing the log and deleting the temporary folder have memory to work with.

## Risks / Trade-offs

- [Risk] On some systems the process is killed before Python can raise `MemoryError` (as on the Linux sandbox, exit 137) → nothing can be reported from inside the process; the estimate before reading remains the main protection.
