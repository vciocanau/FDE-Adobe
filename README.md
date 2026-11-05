# CRM loyalty profile ingestion

A command-line program that reads one customer-profile CSV export from a supermarket chain's CRM, cleans and validates it, and publishes a canonical customer table with campaign eligibility at export time. It also publishes the rejected rows, the losing duplicates, every warning and a run summary. The customer is hypothetical. Every assumption about it is labelled and listed in [`docs/brainstorming/brainstorming.md`](docs/brainstorming/brainstorming.md), with the points to confirm with a real customer in section 8.

**End user:** the data analyst who prepares the marketing database. **Later consumer:** an orchestrator that sends campaigns, for which the outputs are a contract.

## Documents

| Document | What it holds |
| --- | --- |
| [`docs/brainstorming/brainstorming.md`](docs/brainstorming/brainstorming.md) | Map of the problem, assumptions A1–A10, decisions D1–D30 with reasons, what was left out and why |
| [`docs/specification/specification.md`](docs/specification/specification.md) | The contract: input, mapping, field rules, row processing, outputs, codes, operations, 68 acceptance cases (AC-01…AC-68) |
| [`openspec/specs/ingestion/spec.md`](openspec/specs/ingestion/spec.md) | The same specification in OpenSpec form (requirements and WHEN/THEN scenarios) |
| [`docs/plan/2026-11-05-ingest-plan.md`](docs/plan/2026-11-05-ingest-plan.md) | Implementation plan: 19 tasks, each with files, interfaces and the tests written before the code |
| [`docs/ai-log.md`](docs/ai-log.md) | What the AI proposed and what was rejected or changed |

## Setup

Python 3.11 or later. Nothing to install: the program and the tests use the standard library only.

## Run

Windows:

```
py -m ingest run --input path\to\crm_export.csv
```

macOS and Linux:

```
python3 -m ingest run --input path/to/crm_export.csv
```

| Argument | Default | Meaning |
| --- | --- | --- |
| `--input` | required | CRM CSV export |
| `--output` | `runs` | Folder in which run folders are created |
| `--dictionary` | `mappings/synonyms.json` | Approved column-name synonyms |
| `--approve` | none | Mapping proposal file completed by the analyst |
| `--missing-contact-threshold` | 3 | % of canonical customers without a contact channel above which the source probably broke |
| `--rejection-threshold` | 10 | % of rejected rows above which the rate is reported as unusually high |
| `--memory-warn` / `--memory-stop` | 50 / 80 | % of total memory for a warning / a clean stop |
| `--debug` | off | Keeps the temporary folder of a failed run as `failed_YYYY-MM-DD_HHMMSSZ` |

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Run published |
| 1 | Data problem in the file (encoding, unclosed quote, no header, missing card column, …) |
| 2 | Usage, unreadable input, output not writable, run folder already exists |
| 3 | Waiting for the analyst to approve a mapping proposal |
| 4 | Stopped by the memory threshold |
| 5 | Verification failed or unexpected internal error |

Every stop prints one line, `ERROR <CODE> [stage <name>] <message>`. No traceback reaches the operator.

### Approving a new column

When a column is not in the dictionary and the simulated agent proposes a field with a score of 60 or more, the run stops with exit code 3. It writes `runs/mapping_proposals/proposal_<time>Z.json`. The analyst fills in `decision` for each entry: `approve`, `reject` or `change` (with `use_field`). Then the run is repeated with `--approve <that file>`. Approved and changed mappings are added to the dictionary.

## Outputs

Each successful run writes one folder, `runs/run_YYYY-MM-DD_HHMMSSZ` (UTC). The files are written into a temporary folder, verified, and only then renamed, so a run publishes all five files or nothing. Existing run folders are never overwritten.

| File | Content |
| --- | --- |
| `canonical_customers.csv` | One row per card, eligible or not, with `eligible_for_campaign` and `ineligibility_reasons`; unknown columns follow unchanged |
| `rejected_rows.csv` | Every rejected record in full, with all its reason codes in one cell |
| `duplicates.csv` | Every losing duplicate, the winning record and why it lost |
| `warnings.csv` | Every warning, with record number and field |
| `run_summary.json` | Schema version, export date, column mapping, totals, eligibility counts, warnings by code, duration and peak memory of each stage, thresholds and flags |

Totals always reconcile: rows received = canonical + rejected + losing duplicates. The log is written to `runs/logs/` and holds no card, name, email or phone value.

## Architecture

```
CRM CSV ──► read ──────────► clean ─────────────► write ──────────► verify ──► publish (rename)
            strict CSV        field rules           5 files into        re-read files,
            header mapping    rejection             a temporary         reconcile totals
            (dictionary +     duplicates            folder
             simulated agent) eligibility
```

| Module | Responsibility |
| --- | --- |
| `ingest/reader.py` | File checks, delimiter, header, strict record reading |
| `ingest/mapping.py`, `ingest/agent.py` | Dictionary, simulated agent with masked samples, proposal file, approvals |
| `ingest/fields.py` | One rule per field (spec section 6) |
| `ingest/rows.py` | Rejection, duplicates, eligibility, thresholds |
| `ingest/writer.py`, `ingest/publish.py` | Output files, verification, publishing, permissions |
| `ingest/ops.py` | Stage timing, memory readings (Linux, macOS, Windows), memory guard, log |
| `ingest/cli.py` | Arguments, run orchestration, operator messages |

## Main decisions

- **Identity key** is the 16-digit loyalty card. A row without a valid card is rejected, never guessed (D3, D23).
- **Eligibility** needs consent `yes`, subscription `active` and at least one valid contact channel. Unknown never enables a campaign (D9, D11). It is eligibility at export time, not a send authorization (D12).
- **Duplicates:** the most recent valid interaction wins. When the order cannot be known and the rows disagree on consent or subscription, the customer is not eligible (D20).
- **Strict reading:** extra cells with values, text after a closing quote and an unclosed quote are diagnosed, never silently absorbed (D29).
- **The mapping agent is simulated.** There is no API key. It sees only column names and masked samples, and it never approves a mapping by itself (D6, D8, D24).
- **Zero dependencies** (D18).

## Tests

```
python -m unittest -v
```

The suite has 143 tests. Each test's docstring names the acceptance case it proves (AC-01…AC-68) or the spec section. The 100,000-record volume test runs with `INGEST_VOLUME=1`. Synthetic data comes from `python tools/generate_synthetic.py --rows N --out file.csv --seed 42`; it contains invented names only.

## Performance

These are measured runs on a cloud sandbox (Linux, 2 CPUs, 8 GB RAM, Python 3.13) with synthetic files from the generator.

| Run | Records | read | clean | write | verify | total | peak memory |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1x | 100,000 | 0.6 s | 4.1 s | 0.4 s | 0.4 s | 5.5 s | 413 MB |
| 10x | 1,000,000 | 7.1 s | 47.4 s | 4.4 s | 4.3 s | 63.3 s | 3.2 GB |
| 100x | 10,000,000 | killed by the operating system after 19 s in the read stage | | | | | about 8 GB |

Time and memory grow linearly, at about 35 MB of memory per MB of input. **The 100x run was not stopped cleanly by the memory guard.** The whole file is loaded and split into lines before the first memory check at record 10,000, so the operating system ended the process first. This is the price of keeping all results in memory (D16). For 100x the read and clean stages have to stream records instead.

## Known limitations

- A quote in the middle of an unquoted field (`5" pipe`) is read as text and not flagged. The standard CSV reader does not detect it (spec section 4).
- The memory guard cannot stop a file too large to load (see Performance).
- A column that keeps its name but changes its meaning cannot be detected (spec section 5, Out of contract).
- The repeated or skipped local hour is detected only where the system time-zone database is available. Windows has it only with the `tzdata` package; elsewhere the check is skipped silently.

## Not implemented

- A live AI model for mapping (simulated, D8), a real notification for approvals (a JSON file instead), and integration with the orchestrator.
- Encryption of output files (D26); the files are protected by owner-only permissions and the customer's PII policy.
- Streaming for volumes far above 100,000 records (D16).

## AI use

The work followed brainstorming, then specification, then plan, then test-first implementation, with an AI assistant (Claude, with the Superpowers skills). The assistant drafted documents, tests and code. Every rule was decided or approved by the owner, and the assistant's proposals that were rejected or changed are listed in [`docs/ai-log.md`](docs/ai-log.md). Test expectations come from the specification's acceptance cases and were written before the code. Each one was watched failing, then passing. The finished branch was reviewed by a separate AI reviewer that had not seen the work being produced. Its findings and the fixes are recorded in the AI log. Agent instructions are in [`CLAUDE.md`](CLAUDE.md) and [`AGENTS.md`](AGENTS.md).
