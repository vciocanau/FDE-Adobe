# Design

## Context

Peak memory measured on synthetic files, sizes in MiB: 437 MB for an 11.2 MB file (100,000 records, ratio 39) and 3,247 MB for a 112.1 MB file (1,000,000 records, ratio 29). The 10,000,000-record file (1,121 MB) needs about 44 GB by the larger ratio.

## Goals / Non-Goals

**Goals:** a clean, explained stop before reading when the file cannot fit; no behavior change for files that fit.

**Non-Goals:** streaming the read and clean stages (D16 stays); a per-machine calibration of the ratio.

## Decisions

- **Ratio 40, the larger measured ratio (39, in MiB) rounded up.** A first draft used 35, computed with the file size in decimal MB; the re-measurement in MiB gave 39, so the estimate would have been too low at 1x. The smaller ratio at 10x comes from a fixed base cost; taking the larger keeps the estimate on the safe side. Alternative: a fitted line (base + slope) — more precise but needs more measurements than the time allows.
- **Compared against the stop share, not the warning share.** The estimate is coarse; stopping on the warning share would block runs that work.
- **Done in the command line before the read stage, inside the read stage's timing**, so the stop is reported as stage `read` like the other memory stops.

## Risks / Trade-offs

- [Risk] A real customer file may have a different ratio (longer text fields, more columns) → the ratio is logged for every run in the performance log, and a mismatch shows there; the constant is easy to change.
- [Risk] A file just under the limit can still pass the estimate and exceed memory later → the existing checks every 10,000 records still apply.
