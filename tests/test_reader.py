import unittest

from ingest.errors import RunError
from ingest.reader import read_file
from tests.helpers import TempDirTestCase


class ReaderFileTests(TempDirTestCase):
    def read(self, data: bytes):
        return read_file(self.write(data))

    def assertRaisesCode(self, code: str, data: bytes):
        with self.assertRaises(RunError) as e:
            self.read(data)
        self.assertEqual(e.exception.code, code)
        return e.exception

    def test_missing_file(self):
        """AC-01: a path that does not exist gives INPUT_NOT_FOUND naming the path."""
        with self.assertRaises(RunError) as e:
            read_file(self.tmp / "nope.csv")
        self.assertEqual(e.exception.code, "INPUT_NOT_FOUND")
        self.assertIn("nope.csv", e.exception.message)

    def test_folder_is_unreadable(self):
        """AC-02 and Review Focus 2: a folder given as input gives INPUT_UNREADABLE."""
        with self.assertRaises(RunError) as e:
            read_file(self.tmp)
        self.assertEqual(e.exception.code, "INPUT_UNREADABLE")

    def test_empty_file(self):
        """AC-03: a zero-byte file gives INPUT_EMPTY."""
        self.assertRaisesCode("INPUT_EMPTY", b"")

    def test_header_only(self):
        """AC-04: a header only, or a header and blank lines, gives NO_DATA_ROWS."""
        self.assertRaisesCode("NO_DATA_ROWS", b"card_number,email\n")
        self.assertRaisesCode("NO_DATA_ROWS", b"card_number,email\n\n\n")

    def test_no_header(self):
        """AC-05: a first line holding a card number gives NO_HEADER."""
        self.assertRaisesCode("NO_HEADER", b"1234567890123456,a@b.ro\n")
        self.assertRaisesCode("NO_HEADER", b"123,456\n1,2\n")

    def test_delimiters(self):
        """AC-06: semicolon is read like comma; tab stops with UNSUPPORTED_DELIMITER."""
        comma = self.read(b"card_number,email\n1234567890123456,a@b.ro\n")
        semi = self.read(b"card_number;email\n1234567890123456;a@b.ro\n")
        self.assertEqual((semi.delimiter, semi.records[0].cells), (";", comma.records[0].cells))
        e = self.assertRaisesCode("UNSUPPORTED_DELIMITER", b"card_number\temail\n1\t2\n")
        self.assertIn("comma and semicolon", e.message)

    def test_invalid_utf8(self):
        """AC-07: invalid UTF-8 in the header and in a later record gives INVALID_UTF8."""
        self.assertRaisesCode("INVALID_UTF8", b"card_number,em\xffail\n1,2\n")
        e = self.assertRaisesCode("INVALID_UTF8", b"card_number,email\n" + b"1,2\n" * 50 + b"3,\xfe\n")
        self.assertIn("51", e.message)

    def test_bom(self):
        """AC-08: a BOM is ignored; the first column name has no hidden character."""
        r = self.read(b"\xef\xbb\xbfcard_number,email\n1234567890123456,a@b.ro\n")
        self.assertEqual(r.header, ["card_number", "email"])

    def test_line_endings(self):
        """AC-09: LF, CRLF and CR give identical records."""
        body = "card_number,email\n1234567890123456,a@b.ro\n1234567890123457,c@d.ro\n"
        base = [rec.cells for rec in self.read(body.encode()).records]
        for nl in ["\r\n", "\r"]:
            self.assertEqual([rec.cells for rec in self.read(body.replace("\n", nl).encode()).records], base)

    def test_header_names(self):
        """Spec 4 and 6.1: an empty header cell becomes column_<position>; control characters are removed."""
        r = self.read(b"card_number,,Em\x01ail\n1234567890123456,x,a@b.ro\n")
        self.assertEqual(r.header, ["card_number", "column_2", "Email"])
        self.assertEqual([(w.field, w.code) for w in r.warnings], [("Email", "CONTROL_CHARACTER_REMOVED")])


if __name__ == "__main__":
    unittest.main()
