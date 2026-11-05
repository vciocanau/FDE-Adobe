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


H = "card_number,email,first_name\n"


class ReaderRecordTests(TempDirTestCase):
    def read(self, text: str):
        return read_file(self.write(text.encode()))

    def test_extra_cells(self):
        """AC-10: empty extra cells keep the row with TRAILING_EMPTY_CELLS; a value rejects it with EXTRA_CELLS."""
        r = self.read(H + "1111222233334444,a@b.ro,Ana,\n1111222233334445,b@b.ro,Ion,X\n")
        self.assertEqual([(w.record, w.code) for w in r.warnings], [(1, "TRAILING_EMPTY_CELLS")])
        self.assertEqual(r.records[0].cells, ["1111222233334444", "a@b.ro", "Ana"])
        self.assertEqual((r.rejected[0].record, r.rejected[0].codes), (2, ["EXTRA_CELLS"]))
        self.assertEqual(r.rejected[0].original, "1111222233334445,b@b.ro,Ion,X")
        self.assertEqual(r.rows_received, 2)

    def test_short_row(self):
        """AC-11: a short row is kept, missing cells are empty, SHORT_ROW is written."""
        r = self.read(H + "1111222233334444,a@b.ro\n")
        self.assertEqual(r.records[0].cells, ["1111222233334444", "a@b.ro", ""])
        self.assertEqual(r.warnings[0].code, "SHORT_ROW")

    def test_bad_quoting_rejects_only_that_row(self):
        """AC-13: text after a closing quote rejects that row with BAD_QUOTING; reading continues."""
        r = self.read(H + '1111222233334444,a@b.ro,"abc"def\n1111222233334445,b@b.ro,Ion\n')
        self.assertEqual((r.rejected[0].record, r.rejected[0].codes), (1, ["BAD_QUOTING"]))
        self.assertEqual([rec.number for rec in r.records], [2])
        self.assertEqual(r.rows_received, 2)

    def test_multiline(self):
        """AC-14: a quoted field over several lines is kept with MULTILINE_RECORD."""
        r = self.read(H + '1111222233334444,a@b.ro,"Ana\nMaria"\n1111222233334445,b@b.ro,Ion\n')
        self.assertEqual(r.records[0].cells[2], "Ana\nMaria")
        self.assertEqual([(w.record, w.code) for w in r.warnings], [(1, "MULTILINE_RECORD")])
        self.assertEqual(r.records[1].line, 4)

    def test_unclosed_quote_names_start_line(self):
        """AC-15: a quote never closed stops the run with UNCLOSED_QUOTE naming the start line."""
        with self.assertRaises(RunError) as e:
            self.read(H + '1111222233334444,a@b.ro,"unclosed\n1111222233334445,b@b.ro,next\n')
        self.assertEqual(e.exception.code, "UNCLOSED_QUOTE")
        self.assertIn("line 2", e.exception.message)

    def test_record_over_five_lines_stops(self):
        """AC-16: a quote closed by accident 15 lines further down stops the run with UNCLOSED_QUOTE."""
        body = H + '1111222233334444,a@b.ro,"x\n' + "1111222233334445,b@b.ro,y\n" * 14 + 'z"\n'
        with self.assertRaises(RunError) as e:
            self.read(body)
        self.assertEqual(e.exception.code, "UNCLOSED_QUOTE")
        self.assertIn("line 2", e.exception.message)

    def test_five_lines_still_pass(self):
        """AC-14: a record spanning exactly 5 lines is kept."""
        r = self.read(H + '1111222233334444,a@b.ro,"1\n2\n3\n4\n5"\n')
        self.assertEqual(r.records[0].cells[2], "1\n2\n3\n4\n5")

    def test_stray_quote_inside_unquoted_field_is_text(self):
        """AC-17: a quote in the middle of an unquoted field is read as text (known limitation)."""
        self.assertEqual(self.read(H + '1111222233334444,a@b.ro,ab"c\n').records[0].cells[2], 'ab"c')

    def test_very_long_cell(self):
        """Review Focus 1: a cell longer than the csv module's default limit is read whole."""
        r = self.read(H + "1111222233334444,a@b.ro," + "x" * 200_000 + "\n")
        self.assertEqual(len(r.records[0].cells[2]), 200_000)

    def test_counts(self):
        """Spec 4: an empty line is not a record; a line of delimiters is a record."""
        r = self.read(H + "1111222233334444,a,b\n\n,,\n")
        self.assertEqual(r.rows_received, 2)
        self.assertEqual([rec.number for rec in r.records], [1, 2])

    def test_original_has_no_control_characters(self):
        """Spec 6.1 and 8: original_row of a rejected row has no control characters."""
        r = self.read(H + "1111222233334444,a\x01@b.ro,Ion,X\n")
        self.assertEqual(r.rejected[0].original, "1111222233334444,a@b.ro,Ion,X")


if __name__ == "__main__":
    unittest.main()
