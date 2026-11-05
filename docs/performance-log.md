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

## Owner's machine

To be filled from the run on the Windows laptop: the same three runs, with machine, Python version and the log lines `estimated peak` and `Measured peak`.
