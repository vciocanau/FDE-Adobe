import unittest

from ingest.text import match_key, remove_control


class TextTests(unittest.TestCase):
    def test_removes_cc_but_keeps_tab_lf_cr(self):
        """Spec 6.1: control characters are removed; TAB, LF and CR are whitespace and stay."""
        self.assertEqual(remove_control("Ghe\x01orghe\x7f"), ("Gheorghe", True))
        self.assertEqual(remove_control("a\tb\nc\rd"), ("a\tb\nc\rd", False))
        self.assertEqual(remove_control(""), ("", False))

    def test_match_key(self):
        """Spec 5: names are compared after trimming, lowercasing, removing diacritics and separators."""
        for name in ["Loyalty Card", "loyalty_card", "LOYALTY-CARD", " loyalty.card "]:
            self.assertEqual(match_key(name), "loyaltycard")
        self.assertEqual(match_key("Ultima_Interacțiune"), "ultimainteractiune")


if __name__ == "__main__":
    unittest.main()
