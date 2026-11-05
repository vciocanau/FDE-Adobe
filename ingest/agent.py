"""Simulated mapping agent (spec 5, D8): fixed answers plus name similarity. No API key, no network."""
import difflib

from ingest.fields import STATUS_VALUES
from ingest.text import match_key

# Abbreviations a real CRM export might use, with the answer the agent gives for them.
FIXED_ANSWERS = {
    "nrcl": ("card_number", 94, "name looks like a client card number"),
    "nrcard": ("card_number", 94, "name looks like a card number"),
    "mob": ("phone", 75, "abbreviation of mobile"),
    "acordmk": ("subscription", 70, "abbreviation of marketing agreement"),
}


def mask(value: str) -> str:
    """Spec 5: letters become x and digits become 9; status values stay as they are."""
    if value.strip().lower() in STATUS_VALUES:
        return value
    return "".join("9" if ch.isdigit() else "x" if ch.isalpha() else ch for ch in value)


class SimulatedAgent:
    def __init__(self, dictionary: dict[str, list[str]]):
        self.dictionary = dictionary

    def propose(self, column: str, samples: list[str]) -> tuple[str | None, int, str]:
        key = match_key(column)
        if key in FIXED_ANSWERS:
            return FIXED_ANSWERS[key]
        if samples and all(s == "9" * 16 for s in samples):
            return "card_number", 92, "every sample has the shape of a 16-digit card"
        best_field, best_score = None, 0
        for field, names in self.dictionary.items():
            for name in names:
                score = round(difflib.SequenceMatcher(None, key, match_key(name)).ratio() * 100)
                if score > best_score:
                    best_field, best_score = field, score
        return best_field, best_score, f"name similar to a known {best_field} name"
