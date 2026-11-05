# Performance log

Measured runs on synthetic files from `tools/generate_synthetic.py` (seed 42). Each entry records the machine, the input, the duration and peak memory of each stage, the ratio of peak memory to input size, and the outcome. Sizes are in MiB (1 MB here = 1,048,576 bytes).

## 2026-11-05, cloud sandbox: Linux, 2 CPUs, 8,022 MB RAM, Python 3.13

### Before the memory estimate

| Run | Records | Input | read | clean | write | verify | Total | Peak | Peak / input | Outcome |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1x | 100,000 | 11.2 MB | 0.6 s | 4.1 s | 0.4 s | 0.4 s | 5.5 s | 413 MB | 37 | published, totals reconcile |
| 10x | 1,000,000 | 112.1 MB | 7.1 s | 47.4 s | 4.4 s | 4.3 s | 63.3 s | 3,241 MB | 29 | published, totals reconcile |
| 100x | 10,000,000 | 1,121 MB | – | – | – | – | – | – | – | killed by the operating system after 19 s (exit 137), before the first memory check |

### With the memory estimate (change `add-preflight-memory-check`)

| Run | Records | Input | read | clean | write | verify | Total | Peak | Peak / input | Outcome |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1x | 100,000 | 11.2 MB | 0.8 s | 4.0 s | 0.4 s | 0.4 s | 5.5 s | 437 MB | 39.0 | published; canonical 99,096, rejected 291, duplicate losing 613 |
| 10x | 1,000,000 | 112.1 MB | 8.4 s | 42.5 s | 4.6 s | 5.0 s | 60.6 s | 3,247 MB | 29.0 | published; canonical 990,887, rejected 3,023, duplicate losing 6,090 |
| 100x | 10,000,000 | 1,121 MB | – | – | – | – | 0.1 s | – | – | `MEMORY_LIMIT`, exit 4, before reading: estimate 44,826 MB above the limit of 6,418 MB |

Finding: the first estimate used 35 MB per MB, computed with the file size in decimal MB. Measured in MiB the ratio is 39 at 1x and 29 at 10x, so 35 would have underestimated the 1x run (392 MB estimated, 437 MB measured). The constant is 40.

The ratio falls as the file grows because part of the memory is a fixed cost of the program. A fitted line (fixed cost plus a slope) would estimate large files more closely; with only two points it is not done.

## 2026-11-05, desktop: Windows 10 (19045), Intel Core i5-6500 at 3.2 GHz (4 cores), 16,341 MB RAM, Python 3.14.10

These runs used the code from before the memory estimate (commit before `add-preflight-memory-check`), the version on the desktop at the time. Every stage logged `peak memory None MB`: the process peak was not read on Windows, so no peak figure exists for them. That defect is fixed in the change `report-memory-error-as-limit`; the runs are repeated with the fixed code below.

| Run | Records | Input | read | clean | write | verify | Total (stages) | Wall clock | Peak | Outcome |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1x | 100,000 | 11.2 MB | 0.7 s | 6.2 s | 0.5 s | 0.5 s | 7.9 s | 8.3 s | not read | published; canonical 99,096, rejected 291, duplicate losing 613 |
| 10x | 1,000,000 | 112.1 MB | 8.4 s | 63.4 s | 5.1 s | 4.0 s | 80.8 s | 82.7 s | not read | published; canonical 990,887, rejected 3,023, duplicate losing 6,090 |

The counts are the same as on the cloud sandbox, as expected with the same seed. The clean stage is about 1.5 times slower on this machine.

Generating the synthetic files took 2.3 s (1x), 20.6 s (10x) and 198.5 s (100x, 1,121 MB).

### With the fixed code (change `report-memory-error-as-limit`)

| Run | Records | Input | read | clean | write | verify | Total (stages) | Wall clock | Peak | Peak / input | Outcome |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1x | 100,000 | 11.2 MB | 0.7 s | 7.0 s | 0.5 s | 0.6 s | 8.8 s | 9.5 s | 340 MB | 30.3 | published; canonical 99,096, rejected 291, duplicate losing 613; estimate 448 MB |
| 10x | 1,000,000 | 112.1 MB | 8.6 s | 63.6 s | 5.1 s | 3.8 s | 81.2 s | 83.2 s | 3,192 MB | 28.5 | published; canonical 990,887, rejected 3,023, duplicate losing 6,090; estimate 4,483 MB |
| 100x | 10,000,000 | 1,121 MB | – | – | – | – | – | 0.2 s | – | – | `MEMORY_LIMIT`, exit 4, before reading: estimate 44,826 MB above the limit of 13,073 MB |

The process peak is now read on Windows. Both estimates are above the measured peak, so the ratio of 40 is on the safe side on this machine. The ratio is lower than on Linux (30 against 39 at 1x) because Windows reports the peak working set, which counts memory differently from the Linux resident set.

Generating the synthetic files took 2.2 s (1x), 21.6 s (10x) and 208.4 s (100x).

### 100x with the estimate and the stop disabled

An experiment, not a supported setting: the 10,000,000-record file was run with the memory estimate and the stop switched off in a local script, to see where the run fails on this machine.

| Time | Observation |
| --- | --- |
| 0 s | Run starts; about 6 GB of the machine's memory already in use by other programs |
| ~10 s | Machine memory at 80% (12.8 of 16 GB) |
| ~30 s | Physical memory at 95 to 100%; committed memory 23 of 29 GB; Windows moves memory to disk (system disk at 100%) |
| 176 s | Python raises `MemoryError` in the read stage; the run ends with `INTERNAL_ERROR` (exit 5), no traceback, nothing published; the console window closes |

Findings:
- Unlike the Linux sandbox, where the operating system killed the process after 19 s (exit 137), Windows lets the process use the page file and Python gets a `MemoryError`, so the run can report the failure itself.
- The failure was reported with the wrong code; it is now `MEMORY_LIMIT` with exit 4 (AC-69).
- The memory checks every 10,000 records could not stop the run because the Windows peak reading did not work.
- The file needs about 44 GB by the estimate; this machine offers 29 GB including the page file, so 100x needs the read and clean stages to stream records (D16).
