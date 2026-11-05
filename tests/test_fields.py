import unittest

from ingest.fields import clean_card, clean_email, clean_name, clean_phone


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


if __name__ == "__main__":
    unittest.main()
