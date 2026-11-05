"""Run errors (spec section 9): each stops the run with one operator line and an exit code."""

EXIT_CODES = {
    "USAGE": 2, "INPUT_NOT_FOUND": 2, "INPUT_UNREADABLE": 2, "OUTPUT_NOT_WRITABLE": 2,
    "RUN_FOLDER_EXISTS": 2, "INPUT_EMPTY": 1, "NO_DATA_ROWS": 1, "NO_HEADER": 1,
    "UNSUPPORTED_DELIMITER": 1, "INVALID_UTF8": 1, "UNCLOSED_QUOTE": 1,
    "CARD_COLUMN_MISSING": 1, "FIELD_MAPPED_TWICE": 1, "MAPPING_PENDING": 3,
    "MEMORY_LIMIT": 4, "VERIFY_FAILED": 5, "INTERNAL_ERROR": 5,
}


class RunError(Exception):
    def __init__(self, code: str, message: str, stage: str, detail: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.stage = stage
        self.detail = detail
        self.exit_code = EXIT_CODES[code]

    def __str__(self) -> str:
        return f"ERROR {self.code} [stage {self.stage}] {self.message}"
