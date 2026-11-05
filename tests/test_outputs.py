import csv
import json
import unittest

from ingest.errors import RunError
from ingest.models import ColumnMap, Duplicate, Outcome, Rejected, Warning
from ingest.publish import discard, publish, verify
from ingest.rows import OUTPUT_COLUMNS
from ingest.writer import build_summary, write_outputs
from tests.helpers import TempDirTestCase

MAPS = [ColumnMap("card_number", "card_number", "dictionary"), ColumnMap("Religie", None, "passed_through")]


def customer(card="1111222233334444", name="Ana", number=1):
    row = {c: "" for c in OUTPUT_COLUMNS}
    row.update(card_number=card, first_name=name, consent="yes", subscription="active", email="a@b.ro",
               app_installed="unknown", eligible_for_campaign="yes", source_record_number=str(number))
    row["Religie"] = ""
    return row


class OutputTests(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.out = self.tmp / "runs"
        self.out.mkdir()
        self.temp = self.out / ".tmp_run_2026-11-05_083300Z"
        self.run_folder = self.out / "run_2026-11-05_083300Z"

    def clean_outcome(self):
        return Outcome([customer()], [], [], [])

    def summary_for(self, outcome, rows_received):
        return build_summary(run_id="run_2026-11-05_083300Z", run_started_at="2026-11-05T10:33:00+02:00",
                             export_date="2026-11-04", input_name="crm.csv", rows_received=rows_received,
                             maps=MAPS, outcome=outcome,
                             stages={s: {"duration_ms": 1, "peak_memory_mb": 1} for s in ("read", "clean", "write", "verify")},
                             total_ms=4, total_memory_mb=16384,
                             thresholds={"missing_contact_pct": 3, "rejection_pct": 10, "memory_warn_pct": 50, "memory_stop_pct": 80})

    def write_outputs_only(self, outcome, rows_received=None):
        rows_received = rows_received if rows_received is not None else (
            len(outcome.canonical) + len(outcome.rejected) + len(outcome.duplicates))
        self.temp.mkdir()
        summary = self.summary_for(outcome, rows_received)
        write_outputs(self.temp, outcome, MAPS, summary)
        return summary, rows_received

    def write_and_publish(self, outcome):
        summary, rows_received = self.write_outputs_only(outcome)
        verify(self.temp, rows_received)
        publish(self.temp, self.run_folder)
        return json.loads((self.run_folder / "run_summary.json").read_text())

    def lines(self, name):
        return (self.run_folder / name).read_text(encoding="utf-8").splitlines()

    def csv_rows(self, name):
        with open(self.run_folder / name, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def test_five_files_with_headers_when_empty(self):
        """AC-54: all five files exist; empty CSV files keep their headers."""
        self.write_and_publish(self.clean_outcome())
        self.assertEqual(sorted(p.name for p in self.run_folder.iterdir()),
                         ["canonical_customers.csv", "duplicates.csv", "rejected_rows.csv",
                          "run_summary.json", "warnings.csv"])
        self.assertEqual(self.lines("duplicates.csv"),
                         ["card_number,source_record_number,last_interaction_at,kept_record_number,reason"])
        self.assertEqual(self.lines("rejected_rows.csv"), ["source_record_number,reason_codes,reason_text,original_row"])
        self.assertEqual(self.lines("warnings.csv"), ["source_record_number,field,code,message"])

    def test_lf_line_endings(self):
        """Global constraint: written CSV lines end with LF."""
        self.write_and_publish(self.clean_outcome())
        self.assertNotIn(b"\r", (self.run_folder / "canonical_customers.csv").read_bytes())

    def test_rejected_rows_one_line_each(self):
        """AC-55: a rejected row with one error and one with several: one line each, same columns."""
        outcome = Outcome([customer()], [Rejected(2, ["CARD_EMPTY"], ",a"), Rejected(3, ["CARD_INVALID", "EXTRA_CELLS"], "1,b,X")], [], [])
        self.write_and_publish(outcome)
        rows = self.csv_rows("rejected_rows.csv")
        self.assertEqual([r["reason_codes"] for r in rows], ["CARD_EMPTY", "CARD_INVALID;EXTRA_CELLS"])
        self.assertEqual(rows[1]["reason_text"], "Loyalty card is not 16 digits;Row has more cells than the header and an extra cell holds a value")
        self.assertEqual(len({len(r) for r in rows}), 1)

    def test_utf8_without_bom(self):
        """AC-58: names with ș and ț are written in UTF-8 without a BOM and read back identical."""
        self.write_and_publish(Outcome([customer(name="Ștefan Țurcanu")], [], [], []))
        raw = (self.run_folder / "canonical_customers.csv").read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(self.csv_rows("canonical_customers.csv")[0]["first_name"], "Ștefan Țurcanu")

    def test_summary_contract(self):
        """AC-56 and AC-57: schema version and export date in the summary only; stage figures; mapping list."""
        s = self.write_and_publish(self.clean_outcome())
        self.assertEqual((s["schema_version"], s["export_date"]), (1, "2026-11-04"))
        self.assertEqual(list(s["stages"]), ["read", "clean", "write", "verify"])
        self.assertEqual(s["total_duration_ms"], 4)
        self.assertEqual(s["mapping"], [{"column": "card_number", "field": "card_number", "source": "dictionary"},
                                        {"column": "Religie", "field": None, "source": "passed_through"}])
        self.assertEqual(s["destinations"], {"canonical": 1, "rejected": 0, "duplicate_losing": 0, "reconciled": True})
        self.assertNotIn("schema_version", self.csv_rows("canonical_customers.csv")[0])

    def test_totals(self):
        """AC-53: received = canonical + rejected + duplicate losing; warnings are not rows."""
        outcome = Outcome([customer()], [Rejected(3, ["CARD_EMPTY"], ",")],
                          [Duplicate("1111222233334444", 1, "", 2, "LOST_INVALID_TIMESTAMP")],
                          [Warning(2, "email", "EMAIL_INVALID")])
        s = self.write_and_publish(outcome)
        self.assertEqual(s["input"]["rows_received"], 3)
        self.assertEqual(s["warnings"], {"total": 1, "by_code": {"EMAIL_INVALID": 1}})

    def test_verify_failure_publishes_nothing(self):
        """AC-63: a written file that does not match fails verification; nothing is published."""
        self.write_outputs_only(self.clean_outcome())
        (self.temp / "warnings.csv").write_text("broken")
        with self.assertRaises(RunError) as e:
            verify(self.temp, 1)
        self.assertEqual(e.exception.code, "VERIFY_FAILED")
        self.assertFalse(self.run_folder.exists())

    def test_verify_counts(self):
        """Spec 7.4: totals that do not reconcile fail verification."""
        self.write_outputs_only(self.clean_outcome(), rows_received=1)
        with self.assertRaises(RunError) as e:
            verify(self.temp, 2)
        self.assertEqual(e.exception.code, "VERIFY_FAILED")

    def test_existing_run_folder_untouched(self):
        """AC-62: an existing run folder is never overwritten."""
        self.write_outputs_only(self.clean_outcome())
        self.run_folder.mkdir()
        (self.run_folder / "keep.txt").write_text("x")
        with self.assertRaises(RunError) as e:
            publish(self.temp, self.run_folder)
        self.assertEqual(e.exception.code, "RUN_FOLDER_EXISTS")
        self.assertEqual([p.name for p in self.run_folder.iterdir()], ["keep.txt"])

    def test_discard(self):
        """AC-63: on failure the temporary folder is deleted."""
        self.write_outputs_only(self.clean_outcome())
        discard(self.temp, debug=False, failed_name="failed_2026-11-05_083300Z")
        self.assertFalse(self.temp.exists())


if __name__ == "__main__":
    unittest.main()
