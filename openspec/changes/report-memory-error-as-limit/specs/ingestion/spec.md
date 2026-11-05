## ADDED Requirements

### Requirement: Memory that runs out during a run
When the system refuses memory during a run before a memory check could stop it, the system SHALL stop with MEMORY_LIMIT and exit code 4, with the message "Memory ran out in stage <name>; run stopped", SHALL print no traceback, and SHALL publish nothing.

#### Scenario: AC-69
- **WHEN** the system refuses memory during the clean stage
- **THEN** `MEMORY_LIMIT` naming the stage, exit 4, no traceback, nothing published
