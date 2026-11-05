import logging
import sys
import unittest
from unittest import mock

from ingest.errors import RunError
from ingest.ops import MemoryGuard, StageTimer, peak_memory_mb, setup_log, total_memory_mb
from tests.helpers import TempDirTestCase


class OpsTests(TempDirTestCase):
    def test_stage_timer(self):
        """AC-57: each of the four stages has a duration and a peak memory; total is separate."""
        t = StageTimer()
        for stage in ("read", "clean", "write", "verify"):
            with t.stage(stage):
                pass
        self.assertEqual(list(t.results()), ["read", "clean", "write", "verify"])
        self.assertEqual(set(t.results()["read"]), {"duration_ms", "peak_memory_mb"})
        self.assertGreaterEqual(t.total_ms(), sum(v["duration_ms"] for v in t.results().values()))

    def test_memory_readings(self):
        """Spec 10.3: the process peak is read; the total is read or None."""
        self.assertGreater(peak_memory_mb(), 0)
        total = total_memory_mb()
        self.assertTrue(total is None or total > peak_memory_mb())

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_windows_memory(self):
        """Spec 10.3 step 6: on Windows both readings work."""
        self.assertGreater(total_memory_mb(), 0)
        self.assertGreater(peak_memory_mb(), 0)

    def test_log_format(self):
        """Spec 10.1: one line per event with UTC time, level, stage, code and message."""
        path = self.tmp / "logs" / "run.log"
        log = setup_log(path, console=False)
        log.info("Stage finished", extra={"stage": "read", "code": "-"})
        for handler in list(log.handlers):
            handler.close()
            log.removeHandler(handler)
        line = path.read_text(encoding="utf-8").strip()
        self.assertRegex(line, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z INFO read - Stage finished$")


class MemoryGuardTests(unittest.TestCase):
    def test_warning_once_then_stop(self):
        """AC-65: above 50% a warning, once; above 80% a clean stop with MEMORY_LIMIT (exit 4)."""
        guard = MemoryGuard(50, 80, total_mb=1000)
        with mock.patch("ingest.ops.peak_memory_mb", return_value=400):
            self.assertEqual(guard.check("read"), [])
        with mock.patch("ingest.ops.peak_memory_mb", return_value=600):
            self.assertEqual(guard.check("read"), ["MEMORY_WARNING"])
        with mock.patch("ingest.ops.peak_memory_mb", return_value=601):
            self.assertEqual(guard.check("read"), [])
        with mock.patch("ingest.ops.peak_memory_mb", return_value=801), self.assertRaises(RunError) as e:
            guard.check("clean")
        self.assertEqual((e.exception.code, e.exception.exit_code, e.exception.stage), ("MEMORY_LIMIT", 4, "clean"))

    def test_unknown_total(self):
        """AC-65: an unknown total gives MEMORY_TOTAL_UNKNOWN once and skips the check."""
        guard = MemoryGuard(50, 80, total_mb=None)
        self.assertEqual(guard.check("read"), ["MEMORY_TOTAL_UNKNOWN"])
        self.assertEqual(guard.check("clean"), [])


if __name__ == "__main__":
    unittest.main()
