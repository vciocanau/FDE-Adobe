import unittest

from ingest.fields import clean_card, clean_name


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


if __name__ == "__main__":
    unittest.main()
