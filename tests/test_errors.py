import unittest

from ingest.codes import MESSAGES
from ingest.errors import RunError

SECTION_9_CODES = [
    "CARD_EMPTY", "CARD_INVALID", "EXTRA_CELLS", "BAD_QUOTING",
    "LOST_OLDER_TIMESTAMP", "LOST_INVALID_TIMESTAMP", "LOST_TIE_LATER_ROW_WINS",
    "SHORT_ROW", "CONTROL_CHARACTER_REMOVED", "EMAIL_INVALID", "PHONE_INVALID", "PHONE_LEADING_ZERO",
    "TIMESTAMP_UNREADABLE", "TIMESTAMP_OUT_OF_RANGE", "TIMESTAMP_IN_FUTURE", "TIMESTAMP_AMBIGUOUS_HOUR",
    "PURCHASE_AMOUNT_INVALID", "CONSENT_UNKNOWN", "SUBSCRIPTION_UNKNOWN", "APP_INSTALLED_UNKNOWN",
    "NO_CONTACT_CHANNEL", "DUPLICATE_CONFLICT", "DUPLICATE_TIE", "UNKNOWN_COLUMN",
    "CONSENT_COLUMN_MISSING", "SUBSCRIPTION_COLUMN_MISSING", "MISSING_CONTACT_THRESHOLD",
    "REJECTION_RATE_HIGH", "MEMORY_WARNING", "MEMORY_TOTAL_UNKNOWN", "MAPPING_AGENT_FALLBACK",
    "PERMISSIONS_SKIPPED", "TRAILING_EMPTY_CELLS", "MULTILINE_RECORD",
]


class ErrorTests(unittest.TestCase):
    def test_exit_codes(self):
        """Spec 3 and 9: every run error has its exit code."""
        expected = {"USAGE": 2, "INPUT_NOT_FOUND": 2, "INPUT_UNREADABLE": 2, "OUTPUT_NOT_WRITABLE": 2,
                    "RUN_FOLDER_EXISTS": 2, "INPUT_EMPTY": 1, "NO_DATA_ROWS": 1, "NO_HEADER": 1,
                    "UNSUPPORTED_DELIMITER": 1, "INVALID_UTF8": 1, "UNCLOSED_QUOTE": 1,
                    "CARD_COLUMN_MISSING": 1, "FIELD_MAPPED_TWICE": 1, "MAPPING_PENDING": 3,
                    "MEMORY_LIMIT": 4, "VERIFY_FAILED": 5, "INTERNAL_ERROR": 5}
        for code, exit_code in expected.items():
            self.assertEqual(RunError(code, "m", "read").exit_code, exit_code)

    def test_operator_line(self):
        """Spec 9: a run error prints ERROR <CODE> [stage <name>] <message>."""
        self.assertEqual(str(RunError("INPUT_EMPTY", "Input file is empty (0 bytes): a.csv", "read")),
                         "ERROR INPUT_EMPTY [stage read] Input file is empty (0 bytes): a.csv")

    def test_every_section9_code_has_a_message(self):
        """Spec 9: every rejection, duplicate and warning code has a plain-text message."""
        for code in SECTION_9_CODES:
            self.assertIn(code, MESSAGES)
            self.assertTrue(MESSAGES[code])


if __name__ == "__main__":
    unittest.main()
