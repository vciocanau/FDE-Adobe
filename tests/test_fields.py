import unittest
from datetime import datetime, timedelta, timezone

from ingest.fields import clean_card, clean_email, clean_name, clean_phone, parse_timestamp, timestamp_sort_key


class CardTests(unittest.TestCase):
    def test_valid_forms_give_one_key(self):
        """AC-45: the same card with spaces in groups of 5, 9 and 2 digits, with dashes, or without spaces."""
        self.assertEqual(clean_card("12345 678901234 56").value, "1234567890123456")
        self.assertEqual(clean_card("1234-5678-9012-3456").value, "1234567890123456")
        self.assertEqual(clean_card("0012345678901234").value, "0012345678901234")

    def test_invalid_cards(self):
        """AC-27: short, letters, empty and Excel notation are rejected; digits of other scripts too (spec 6.2)."""
        for raw, code in [("1234 5678", "CARD_INVALID"), ("12345678901234AB", "CARD_INVALID"),
                          ("", "CARD_EMPTY"), ("1.23457E+15", "CARD_INVALID"),
                          ("１２３４５６７８９０１２３４５６", "CARD_INVALID")]:
            self.assertIn(code, clean_card(raw).codes, raw)

    def test_control_character_in_card(self):
        """AC-28: a 16-digit card with a control character is valid; with 15 digits it is rejected."""
        r = clean_card("12345678\x0190123456")
        self.assertEqual((r.value, r.codes), ("1234567890123456", ["CONTROL_CHARACTER_REMOVED"]))
        self.assertIn("CARD_INVALID", clean_card("1234567\x0190123456").codes)


class NameTests(unittest.TestCase):
    def test_control_character(self):
        """AC-26: Gheorghe followed by U+0001 is stored as Gheorghe with the warning."""
        r = clean_name("Gheorghe\x01")
        self.assertEqual((r.value, r.codes), ("Gheorghe", ["CONTROL_CHARACTER_REMOVED"]))

    def test_cedilla_and_comma_below_are_identical(self):
        """AC-29: cedilla and comma-below forms give the identical value."""
        self.assertEqual(clean_name("Ştefan Ţurcanu").value, clean_name("Ștefan Țurcanu").value)
        self.assertEqual(clean_name("Ştefan Ţurcanu").value, "Ștefan Țurcanu")

    def test_spaces_and_nfc(self):
        """AC-30: trimmed, inner spaces collapsed, stored in NFC."""
        self.assertEqual(clean_name("  Ana   Maria ").value, "Ana Maria")
        self.assertEqual(clean_name("Ioané").value, "Ioané")

    def test_empty_names(self):
        """AC-31: an empty name stays empty with no warning; only control characters give the warning."""
        self.assertEqual((clean_name("").value, clean_name("").codes), ("", []))
        self.assertEqual(clean_name("\x01\x02").codes, ["CONTROL_CHARACTER_REMOVED"])


class PhoneTests(unittest.TestCase):
    def test_romanian_forms(self):
        """AC-32: 0722123456, 0040722123456 and +40722123456 give +40722123456."""
        for raw in ["0722123456", "0040722123456", "+40722123456", "0722 123 456", "(0722)-123.456"]:
            self.assertEqual(clean_phone(raw).value, "+40722123456", raw)

    def test_lost_leading_zero(self):
        """AC-32: a nine-digit number starting with 7 gets +40 and PHONE_LEADING_ZERO."""
        r = clean_phone("722123456")
        self.assertEqual((r.value, r.codes), ("+40722123456", ["PHONE_LEADING_ZERO"]))

    def test_other_country_and_invalid(self):
        """AC-32: another country prefix is kept; 12345 is emptied with PHONE_INVALID; empty stays empty."""
        self.assertEqual(clean_phone("+4915112345678").value, "+4915112345678")
        self.assertEqual((clean_phone("12345").value, clean_phone("12345").codes), ("", ["PHONE_INVALID"]))
        self.assertEqual(clean_phone("").codes, [])


class EmailTests(unittest.TestCase):
    def test_trim_and_lowercase(self):
        """AC-33: an email with surrounding spaces and capitals is trimmed and lowercased."""
        self.assertEqual(clean_email(" Ana@Example.COM ").value, "ana@example.com")

    def test_invalid(self):
        """AC-33: a space inside, two @ or no dot after the @ empties the email with EMAIL_INVALID."""
        for raw in ["ana @example.com", "ana@@example.com", "ana@example"]:
            r = clean_email(raw)
            self.assertEqual((r.value, r.codes), ("", ["EMAIL_INVALID"]), raw)
        self.assertEqual(clean_email("").codes, [])


RUN = datetime(2026, 11, 5, 12, 0, tzinfo=timezone(timedelta(hours=2)))


class DateTests(unittest.TestCase):
    def test_three_formats_day_first(self):
        """AC-34: 2026-11-04, 04.11.2026 and 04/11/2026 give the same stored value."""
        for raw in ["2026-11-04", "04.11.2026", "04/11/2026"]:
            self.assertEqual(parse_timestamp(raw, RUN).value, "2026-11-04", raw)

    def test_date_with_time_and_zone(self):
        """AC-34 and spec 6.6: a time after a space or T; an ISO value may carry Z or an offset."""
        self.assertEqual(parse_timestamp("2026-11-04 14:30", RUN).value, "2026-11-04T14:30:00")
        self.assertEqual(parse_timestamp("04.11.2026T14:30:15", RUN).value, "2026-11-04T14:30:15")
        self.assertEqual(parse_timestamp("2026-11-04T14:30:00+02:00", RUN).value, "2026-11-04T14:30:00+02:00")
        self.assertEqual(parse_timestamp("2026-11-04T12:30:00Z", RUN).value, "2026-11-04T12:30:00+00:00")

    def test_unreadable(self):
        """AC-34: month-first, impossible dates and text are emptied with TIMESTAMP_UNREADABLE."""
        for raw in ["11/13/2026", "13.13.2026", "31.02.2026", "abc"]:
            r = parse_timestamp(raw, RUN)
            self.assertEqual((r.value, r.codes), ("", ["TIMESTAMP_UNREADABLE"]), raw)

    def test_out_of_range_and_future(self):
        """AC-35: year 0001 with an offset and a value after the run time are emptied with their warnings."""
        self.assertEqual(parse_timestamp("0001-01-01T00:00:00+01:00", RUN).codes, ["TIMESTAMP_OUT_OF_RANGE"])
        self.assertEqual(parse_timestamp("2026-11-06", RUN).codes, ["TIMESTAMP_IN_FUTURE"])
        self.assertEqual(parse_timestamp("", RUN).codes, [])

    def test_sort_key(self):
        """Spec 6.6 step 8: a date alone counts as 00:00:00 local time when compared."""
        self.assertLess(timestamp_sort_key("2026-11-04"), timestamp_sort_key("2026-11-04T00:00:01"))


if __name__ == "__main__":
    unittest.main()
