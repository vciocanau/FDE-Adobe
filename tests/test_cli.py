import contextlib
import io
import json
import shutil
import time
import unittest
from pathlib import Path
from unittest import mock

from ingest.cli import main
from tests.helpers import TempDirTestCase

FIXTURES = Path(__file__).resolve().parent / "fixtures"
DICTIONARY = Path(__file__).resolve().parent.parent / "mappings" / "synonyms.json"


class CliTests(TempDirTestCase):
    """small.csv holds 4 records worked out by hand: record 2 is a newer duplicate of record 1 and wins;
    record 3 has no card and is rejected; record 4 has an invalid email (warning) and consent no.
    Expected: received 4 = canonical 2 + rejected 1 + duplicate losing 1."""

    def setUp(self):
        super().setUp()
        self.out = self.tmp / "runs"
        self.dictionary = self.tmp / "synonyms.json"
        shutil.copy(DICTIONARY, self.dictionary)

    def cli(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(args)
        return code, out.getvalue(), err.getvalue()

    def small_args(self, *extra):
        return ["run", "--input", str(FIXTURES / "small.csv"), "--output", str(self.out),
                "--dictionary", str(self.dictionary), *extra]

    def run_folders(self):
        return sorted(p for p in self.out.glob("run_*") if p.is_dir()) if self.out.exists() else []

    def temp_folders(self):
        return sorted(p for p in self.out.iterdir() if p.name.startswith((".tmp_", "failed_"))) if self.out.exists() else []

    def only_run_folder(self):
        folders = self.run_folders()
        self.assertEqual(len(folders), 1)
        return folders[0]

    def test_success(self):
        """AC-53 and AC-59: exit 0, one run folder named in UTC with Z, totals reconcile."""
        code, out, err = self.cli(self.small_args())
        self.assertEqual(code, 0, err)
        folder = self.only_run_folder()
        self.assertRegex(folder.name, r"^run_\d{4}-\d{2}-\d{2}_\d{6}Z$")
        summary = json.loads((folder / "run_summary.json").read_text())
        self.assertEqual(summary["destinations"], {"canonical": 2, "rejected": 1, "duplicate_losing": 1, "reconciled": True})
        self.assertEqual(self.temp_folders(), [])

    def test_usage(self):
        """Spec 3: a missing --input or a threshold outside 0 to 100 is a usage error, exit 2."""
        self.assertEqual(self.cli(["run"])[0], 2)
        code, _, err = self.cli(["run", "--input", "x.csv", "--memory-stop", "120"])
        self.assertEqual(code, 2)
        self.assertIn("ERROR USAGE", err)

    def test_input_not_found(self):
        """AC-01: a missing input gives INPUT_NOT_FOUND, exit 2, no result files, no traceback."""
        code, _, err = self.cli(["run", "--input", str(self.tmp / "nope.csv"), "--output", str(self.out),
                                 "--dictionary", str(self.dictionary)])
        self.assertEqual(code, 2)
        self.assertIn("ERROR INPUT_NOT_FOUND", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(self.run_folders(), [])

    def test_input_is_a_folder(self):
        """AC-02 and Review Focus 2: a folder as input gives INPUT_UNREADABLE, exit 2."""
        code, _, err = self.cli(["run", "--input", str(self.tmp), "--output", str(self.out),
                                 "--dictionary", str(self.dictionary)])
        self.assertEqual(code, 2)
        self.assertIn("ERROR INPUT_UNREADABLE", err)

    def test_output_is_a_file(self):
        """AC-61 and Review Focus 3: an output path that is a file gives OUTPUT_NOT_WRITABLE, exit 2."""
        f = self.tmp / "file"
        f.write_text("x")
        code, _, err = self.cli(["run", "--input", str(FIXTURES / "small.csv"), "--output", str(f),
                                 "--dictionary", str(self.dictionary)])
        self.assertEqual(code, 2)
        self.assertIn("ERROR OUTPUT_NOT_WRITABLE", err)
        self.assertEqual(f.read_text(), "x")

    def test_internal_error_has_no_traceback(self):
        """AC-64: an unexpected error names the stage, exit 5, no traceback, nothing published."""
        with mock.patch("ingest.rows.process", side_effect=ZeroDivisionError):
            code, _, err = self.cli(self.small_args())
        self.assertEqual(code, 5)
        self.assertIn("ERROR INTERNAL_ERROR [stage clean]", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(self.run_folders(), [])

    def test_failure_after_some_files_written(self):
        """AC-63: a failure after some files were written publishes nothing and leaves no temporary folder."""
        with mock.patch("ingest.writer.write_duplicates", side_effect=OSError("disk full")):
            code, _, err = self.cli(self.small_args())
        self.assertEqual(code, 2)
        self.assertIn("ERROR OUTPUT_NOT_WRITABLE [stage write]", err)
        self.assertEqual((self.run_folders(), self.temp_folders()), ([], []))

    def test_same_input_twice_same_files(self):
        """AC-60: the same input run twice gives the same files."""
        self.cli(self.small_args())
        time.sleep(1.1)
        self.cli(self.small_args())
        first, second = self.run_folders()
        for name in ("canonical_customers.csv", "rejected_rows.csv", "warnings.csv", "duplicates.csv"):
            self.assertEqual((first / name).read_bytes(), (second / name).read_bytes(), name)

    def test_log_has_no_personal_values(self):
        """AC-67: the log holds no card, name, email or phone value."""
        self.cli(self.small_args())
        logs = list((self.out / "logs").glob("run_*.log"))
        self.assertEqual(len(logs), 1)
        text = logs[0].read_text()
        self.assertIn("INFO", text)
        for value in ("1111222233334444", "ana@example.com", "+40722123456", "Gheorghe", "Maria"):
            self.assertNotIn(value, text)

    def test_mapping_pending_exit_3(self):
        """AC-21: a proposal stops the run with exit 3 and nothing published."""
        data = (FIXTURES / "small.csv").read_text().replace("card_number,", "NrCl,", 1)
        path = self.write(data.encode())
        code, _, err = self.cli(["run", "--input", str(path), "--output", str(self.out), "--dictionary", str(self.dictionary)])
        self.assertEqual(code, 3)
        self.assertIn("ERROR MAPPING_PENDING", err)
        self.assertEqual(self.run_folders(), [])


if __name__ == "__main__":
    unittest.main()
