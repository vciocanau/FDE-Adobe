"""Shared test helpers."""
import shutil
import tempfile
import unittest
from pathlib import Path


class TempDirTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ingest_test_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, data: bytes, name: str = "input.csv") -> Path:
        path = self.tmp / name
        path.write_bytes(data)
        return path
