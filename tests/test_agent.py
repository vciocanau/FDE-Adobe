import json
import shutil
import unittest
from datetime import datetime, timezone

from ingest.agent import SimulatedAgent, mask
from ingest.errors import RunError
from ingest.mapping import apply_approval, band, load_dictionary, map_header_with_samples, resolve_mapping
from ingest.text import match_key
from tests.helpers import TempDirTestCase
from tests.test_mapping import DICTIONARY

NOW = datetime(2026, 11, 5, 8, 33, tzinfo=timezone.utc)


class RecordingAgent:
    def __init__(self, answers=None):
        self.calls = []
        self.answers = answers or {"NrCl": ("card_number", 94, "name looks like a client card")}

    def propose(self, column, samples):
        self.calls.append((column, samples))
        return self.answers.get(column, (None, 10, "no clear match"))


class MaskTests(unittest.TestCase):
    def test_mask(self):
        """AC-24: letters become x, digits become 9, other signs stay; status values stay unmasked."""
        self.assertEqual(mask("ion@x.ro"), "xxx@x.xx")
        self.assertEqual(mask("0722 123"), "9999 999")
        self.assertEqual(mask("Da"), "Da")
        self.assertEqual(mask("Activ"), "Activ")

    def test_bands(self):
        """Spec 5 (A6): above 90 safe, 60 to 90 caution, below 60 none."""
        self.assertEqual([band(s) for s in (94, 90, 60, 59)], ["safe", "caution", "caution", "none"])

    def test_simulated_agent(self):
        """Spec 5 (D8): the simulated agent proposes from fixed answers and name similarity."""
        agent = SimulatedAgent(load_dictionary(DICTIONARY))
        self.assertEqual(agent.propose("NrCl", [])[:2], ("card_number", 94))
        field, score, _ = agent.propose("Zzqx", ["xx"])
        self.assertLess(score, 60)


class AgentInputTests(TempDirTestCase):
    def test_agent_sees_only_names_and_three_masked_samples(self):
        """AC-24: the agent receives the column name and at most 3 masked samples, no complete row."""
        agent = RecordingAgent()
        rows = [["1234567890123456", "a@b.ro"]] * 5
        map_header_with_samples(["NrCl", "email"], rows, load_dictionary(DICTIONARY), agent)
        self.assertEqual(agent.calls, [("NrCl", ["9999999999999999"] * 3)])


class ProposalTests(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.dictionary_path = self.tmp / "synonyms.json"
        shutil.copy(DICTIONARY, self.dictionary_path)
        self.out = self.tmp / "runs"

    def run_mapping(self, header, approve=None, agent=None):
        rows = [["x"] * len(header)]
        return resolve_mapping(header, rows, self.dictionary_path, self.out, "crm.csv",
                               agent or RecordingAgent({"NrCl": ("card_number", 94, "client card"),
                                                        "Mob": ("phone", 75, "mobile"),
                                                        "C7": (None, 41, "no clear match")}),
                               approve, NOW)

    def only_proposal(self):
        files = list((self.out / "mapping_proposals").glob("proposal_*.json"))
        self.assertEqual(len(files), 1)
        return files[0]

    def test_stop_and_proposal_file(self):
        """AC-21: proposals of 60 or more stop the run with MAPPING_PENDING and write the proposal file."""
        with self.assertRaises(RunError) as e:
            self.run_mapping(["NrCl", "Mob", "C7", "email"])
        self.assertEqual(e.exception.code, "MAPPING_PENDING")
        path = self.only_proposal()
        self.assertEqual(path.name, "proposal_2026-11-05_083300Z.json")
        proposal = json.loads(path.read_text())
        self.assertEqual(set(proposal), {"schema_version", "proposal_id", "input_file", "proposals"})
        self.assertEqual([(p["column"], p["field"], p["band"]) for p in proposal["proposals"]],
                         [("NrCl", "card_number", "safe"), ("Mob", "phone", "caution"), ("C7", None, "none")])
        self.assertEqual(set(proposal["proposals"][0]),
                         {"column", "field", "score", "band", "reason", "decision", "use_field"})

    def decide(self, decisions):
        with self.assertRaises(RunError):
            self.run_mapping(["NrCl", "Mob", "C7", "email"])
        path = self.only_proposal()
        data = json.loads(path.read_text())
        for p in data["proposals"]:
            p["decision"], p["use_field"] = decisions.get(p["column"], ("", ""))
        path.write_text(json.dumps(data))
        return path

    def test_approvals(self):
        """AC-22: approve and change are applied and saved in the dictionary; reject passes the column through."""
        path = self.decide({"NrCl": ("approve", ""), "Mob": ("reject", ""), "C7": ("change", "last_name")})
        maps, warnings = self.run_mapping(["NrCl", "Mob", "C7", "email"], approve=path)
        self.assertEqual([(m.field, m.source) for m in maps],
                         [("card_number", "approved"), (None, "passed_through"),
                          ("last_name", "approved"), ("email", "dictionary")])
        self.assertIn(("Mob", "UNKNOWN_COLUMN"), [(w.field, w.code) for w in warnings])
        saved = load_dictionary(self.dictionary_path)
        self.assertIn("nrcl", [match_key(n) for n in saved["card_number"]])
        self.assertIn("c7", [match_key(n) for n in saved["last_name"]])

    def test_change_to_unknown_field_is_usage(self):
        """AC-22: a change to an unknown field is a USAGE error."""
        path = self.decide({"NrCl": ("change", "fax"), "Mob": ("reject", "")})
        with self.assertRaises(RunError) as e:
            apply_approval(path, ["NrCl", "Mob"], self.dictionary_path)
        self.assertEqual(e.exception.code, "USAGE")

    def test_missing_decision_stops_again(self):
        """Spec 5: a proposal of 60 or more without a decision stops the run again with MAPPING_PENDING."""
        path = self.decide({"NrCl": ("approve", "")})
        with self.assertRaises(RunError) as e:
            apply_approval(path, ["NrCl", "Mob"], self.dictionary_path)
        self.assertEqual(e.exception.code, "MAPPING_PENDING")


if __name__ == "__main__":
    unittest.main()
