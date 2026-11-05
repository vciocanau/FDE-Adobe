## ADDED Requirements

### Requirement: Memory estimate before reading
Before reading the input, the system SHALL estimate the run's peak memory as 40 MB per MB of input file, and SHALL stop with MEMORY_LIMIT and exit code 4, without reading the file and without publishing anything, when the estimate is above the memory-stop share of total memory. When total memory cannot be read, the estimate SHALL be skipped.

#### Scenario: File too large for this machine
- **WHEN** the input file is 200 MB and total memory is 8,000 MB with the default stop share of 80%
- **THEN** the estimate of 8,000 MB is above 6,400 MB and the run stops with MEMORY_LIMIT, exit 4, before the read stage reads any record

#### Scenario: File that fits
- **WHEN** the input file is 100 MB and total memory is 8,000 MB with the default stop share of 80%
- **THEN** the estimate of 4,000 MB is below 6,400 MB and the run proceeds normally

#### Scenario: Total memory unknown
- **WHEN** total memory cannot be read
- **THEN** no estimate is made, MEMORY_TOTAL_UNKNOWN is recorded once, and the run proceeds
