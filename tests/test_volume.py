import json
import os
import unittest

from ingest.cli import main
from tests.helpers import TempDirTestCase
from tests.test_cli import DICTIONARY
from tools.generate_synthetic import generate


class GeneratorTests(TempDirTestCase):
    def test_deterministic(self):
        """Spec 11.7: the generator takes the number of records and a seed and is deterministic."""
        a, b = self.tmp / "a.csv", self.tmp / "b.csv"
        generate(rows=500, out=a, seed=42)
        generate(rows=500, out=b, seed=42)
        self.assertEqual(a.read_bytes(), b.read_bytes())
        self.assertEqual(len(a.read_text(encoding="utf-8").splitlines()), 501)

    def test_small_file_runs_clean(self):
        """Spec 11.7: a generated file runs end to end without a mapping stop."""
        path = self.tmp / "s.csv"
        generate(rows=2000, out=path, seed=7)
        self.assertEqual(main(["run", "--input", str(path), "--output", str(self.tmp / "runs"),
                               "--dictionary", str(DICTIONARY)]), 0)


@unittest.skipUnless(os.environ.get("INGEST_VOLUME") == "1", "set INGEST_VOLUME=1 to run")
class VolumeTest(TempDirTestCase):
    def test_100k(self):
        """AC-68: a synthetic file of 100,000 records completes; stage figures in the summary; totals reconcile."""
        path = self.tmp / "synthetic_100k.csv"
        generate(rows=100_000, out=path, seed=42)
        out = self.tmp / "runs"
        self.assertEqual(main(["run", "--input", str(path), "--output", str(out), "--dictionary", str(DICTIONARY)]), 0)
        summary = json.loads(next(out.glob("run_*/run_summary.json")).read_text())
        self.assertTrue(summary["destinations"]["reconciled"])
        self.assertEqual(summary["input"]["rows_received"], 100_000)
        for stage in ("read", "clean", "write", "verify"):
            self.assertGreater(summary["stages"][stage]["duration_ms"], 0)
        print("\n" + json.dumps({"stages": summary["stages"], "total_duration_ms": summary["total_duration_ms"]}))


if __name__ == "__main__":
    unittest.main()
