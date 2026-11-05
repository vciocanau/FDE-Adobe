import unittest
from pathlib import Path

from ingest.errors import RunError
from ingest.mapping import load_dictionary, map_header, mapping_warnings

DICTIONARY = Path(__file__).resolve().parent.parent / "mappings" / "synonyms.json"


class DictionaryMappingTests(unittest.TestCase):
    def setUp(self):
        self.dictionary = load_dictionary(DICTIONARY)

    def test_dictionary_names(self):
        """AC-20 and spec 5: dictionary names map; an unknown name is passed through."""
        maps, proposals = map_header(["Loyalty Card", "E-mail", "Tel. Mobil", "Religie"], self.dictionary)
        self.assertEqual([(m.column, m.field, m.source) for m in maps],
                         [("Loyalty Card", "card_number", "dictionary"), ("E-mail", "email", "dictionary"),
                          ("Tel. Mobil", "phone", "dictionary"), ("Religie", None, "passed_through")])
        self.assertEqual(proposals, [])
        self.assertEqual([(w.field, w.code) for w in mapping_warnings(maps)], [("Religie", "UNKNOWN_COLUMN")])

    def test_canonical_name_maps_to_itself(self):
        """Spec 8: a column already named like a canonical field maps to that field."""
        maps, _ = map_header(["card_number", "last_interaction_at", "last_purchase_at"], self.dictionary)
        self.assertEqual([m.field for m in maps], ["card_number", "last_interaction_at", "last_purchase_at"])

    def test_whole_name_only(self):
        """Spec 5: a part of a name never matches."""
        maps, _ = map_header(["card_number", "email_backup"], self.dictionary)
        self.assertIsNone(maps[1].field)

    def test_duplicate_unknown_names_get_suffixes(self):
        """Spec 4: unknown columns with the same name get _2, _3."""
        maps, _ = map_header(["card", "X", "X", "X"], self.dictionary)
        self.assertEqual([m.column for m in maps], ["card", "X", "X_2", "X_3"])

    def test_missing_card(self):
        """AC-18: no column maps to the card: CARD_COLUMN_MISSING."""
        with self.assertRaises(RunError) as e:
            map_header(["email", "phone"], self.dictionary)
        self.assertEqual(e.exception.code, "CARD_COLUMN_MISSING")

    def test_field_twice(self):
        """AC-19: two columns map to the same field: FIELD_MAPPED_TWICE naming both."""
        with self.assertRaises(RunError) as e:
            map_header(["card", "card_number", "email"], self.dictionary)
        self.assertEqual(e.exception.code, "FIELD_MAPPED_TWICE")
        self.assertIn("card_number", e.exception.message)


if __name__ == "__main__":
    unittest.main()
