import unittest
from datetime import datetime, timedelta, timezone
from itertools import product

from ingest.models import ColumnMap, RawRecord, ReadResult
from ingest.models import Outcome, Rejected
from ingest.rows import process, run_flags

RUN = datetime(2026, 11, 5, 12, 0, tzinfo=timezone(timedelta(hours=2)))
HEADER = ["card_number", "consent", "subscription", "email", "app_installed", "last_interaction_at", "Religie"]


class RowTests(unittest.TestCase):
    def run_rows(self, rows, app="", drop=(), ts="2026-01-01"):
        header = [h for h in HEADER if h not in drop]
        records = []
        for number, (card, consent, subscription, email) in enumerate(rows, start=1):
            values = {"card_number": card, "consent": consent, "subscription": subscription, "email": email,
                      "app_installed": app, "last_interaction_at": ts, "Religie": ""}
            cells = [values[h] for h in header]
            records.append(RawRecord(number, number + 1, cells, ",".join(cells)))
        return self.process(header, records)

    def run_rows_ts(self, rows, subscriptions=None):
        records = []
        for number, (card, consent, ts) in enumerate(rows, start=1):
            subscription = subscriptions[number - 1] if subscriptions else "activ"
            cells = [card, consent, subscription, "a@b.ro", "", ts, ""]
            records.append(RawRecord(number, number + 1, cells, ",".join(cells)))
        return self.process(HEADER, records)

    def process(self, header, records):
        maps = [ColumnMap(h, None if h == "Religie" else h, "passed_through" if h == "Religie" else "dictionary")
                for h in header]
        read = ReadResult(header, ",", records, [], [], len(records))
        return process(read, maps, RUN)

    def reasons(self, out, card):
        return next(r for r in out.canonical if r["card_number"] == card)["ineligibility_reasons"]

    def test_nine_combinations(self):
        """AC-40: only consent yes and subscription active is eligible; all nine stay canonical."""
        combos = list(product(["da", "nu", "x"], ["activ", "inactiv", "x"]))
        out = self.run_rows([("1%015d" % i, c, s, "a@b.ro") for i, (c, s) in enumerate(combos)])
        self.assertEqual(len(out.canonical), 9)
        self.assertEqual([r["card_number"] for r in out.canonical if r["eligible_for_campaign"] == "yes"],
                         ["1000000000000000"])
        self.assertEqual(self.reasons(out, "1000000000000004"), "CONSENT_NOT_YES;SUBSCRIPTION_NOT_ACTIVE")
        codes = {w.code for w in out.warnings}
        self.assertTrue({"CONSENT_UNKNOWN", "SUBSCRIPTION_UNKNOWN"} <= codes)

    def test_canonical_columns(self):
        """Spec 8: canonical columns in order, then pass-through columns."""
        out = self.run_rows([("1111222233334444", "da", "activ", "a@b.ro")])
        self.assertEqual(list(out.canonical[0]),
                         ["card_number", "first_name", "last_name", "email", "phone", "app_installed", "consent",
                          "subscription", "last_interaction_at", "last_purchase_at", "last_purchase_amount",
                          "eligible_for_campaign", "ineligibility_reasons", "source_record_number", "Religie"])

    def test_no_contact(self):
        """AC-41: consent yes, subscription active and no channel: not eligible with NO_CONTACT_CHANNEL."""
        out = self.run_rows([("1111222233334444", "da", "activ", "")], app="nu")
        self.assertEqual(self.reasons(out, "1111222233334444"), "NO_CONTACT_CHANNEL")
        self.assertIn("NO_CONTACT_CHANNEL", [w.code for w in out.warnings])

    def test_app_is_a_channel(self):
        """Spec 7.3: app installed yes is a contact channel."""
        out = self.run_rows([("1111222233334444", "da", "activ", "")], app="da")
        self.assertEqual(out.canonical[0]["eligible_for_campaign"], "yes")

    def test_missing_consent_column(self):
        """AC-42: no consent column: CONSENT_COLUMN_MISSING instead of CONSENT_NOT_YES, plus the run warning."""
        out = self.run_rows([("1111222233334444", None, "activ", "a@b.ro")], drop=["consent"])
        self.assertEqual(self.reasons(out, "1111222233334444"), "CONSENT_COLUMN_MISSING")
        self.assertIn("CONSENT_COLUMN_MISSING", [w.code for w in out.warnings if w.record is None])

    def test_missing_subscription_column(self):
        """AC-42: no subscription column: SUBSCRIPTION_COLUMN_MISSING."""
        out = self.run_rows([("1111222233334444", "da", None, "a@b.ro")], drop=["subscription"])
        self.assertEqual(self.reasons(out, "1111222233334444"), "SUBSCRIPTION_COLUMN_MISSING")

    def test_newer_withdrawal_wins(self):
        """AC-43: the newer row withdraws consent and wins; the older row loses with LOST_OLDER_TIMESTAMP."""
        out = self.run_rows_ts([("1111222233334444", "da", "2026-01-01"), ("1111222233334444", "nu", "2026-02-01")])
        self.assertEqual(out.canonical[0]["source_record_number"], "2")
        self.assertEqual(out.canonical[0]["eligible_for_campaign"], "no")
        self.assertEqual((out.duplicates[0].record, out.duplicates[0].kept_record, out.duplicates[0].reason),
                         (1, 2, "LOST_OLDER_TIMESTAMP"))

    def test_tie(self):
        """AC-44: same timestamp or both missing: the later record wins with DUPLICATE_TIE."""
        for ts in ("2026-01-01", ""):
            out = self.run_rows_ts([("1111222233334444", "da", ts), ("1111222233334444", "da", ts)])
            self.assertEqual(out.canonical[0]["source_record_number"], "2")
            self.assertEqual(out.duplicates[0].reason, "LOST_TIE_LATER_ROW_WINS")
            self.assertIn("DUPLICATE_TIE", [w.code for w in out.warnings])

    def test_card_spacing_is_one_key(self):
        """AC-45: the same card with and without spaces is one key."""
        out = self.run_rows_ts([("11112 222333344 44", "da", "2026-01-01"), ("1111222233334444", "da", "2026-02-01")])
        self.assertEqual((len(out.canonical), len(out.duplicates)), (1, 1))

    def test_future_timestamp_loses(self):
        """AC-46: a future timestamp is emptied; the row with the real timestamp wins with LOST_INVALID_TIMESTAMP."""
        out = self.run_rows_ts([("1111222233334444", "da", "2026-01-01"), ("1111222233334444", "da", "2099-01-01")])
        self.assertEqual(out.canonical[0]["source_record_number"], "1")
        self.assertEqual(out.duplicates[0].reason, "LOST_INVALID_TIMESTAMP")
        self.assertIn("TIMESTAMP_IN_FUTURE", [w.code for w in out.warnings])
        self.assertNotIn("CONFLICTING_DUPLICATES", out.canonical[0]["ineligibility_reasons"])

    def test_conflict_with_missing_timestamp(self):
        """AC-47: one timestamp missing and the rows disagree on consent: CONFLICTING_DUPLICATES."""
        out = self.run_rows_ts([("1111222233334444", "nu", ""), ("1111222233334444", "da", "2026-01-01")])
        self.assertIn("CONFLICTING_DUPLICATES", out.canonical[0]["ineligibility_reasons"])
        self.assertIn("DUPLICATE_CONFLICT", [w.code for w in out.warnings])

    def test_conflict_on_tie(self):
        """AC-48: same timestamp, rows disagree on subscription: later wins, CONFLICTING_DUPLICATES."""
        out = self.run_rows_ts([("1111222233334444", "da", "2026-01-01"), ("1111222233334444", "da", "2026-01-01")],
                               subscriptions=["activ", "inactiv"])
        self.assertEqual(out.canonical[0]["source_record_number"], "2")
        self.assertIn("CONFLICTING_DUPLICATES", out.canonical[0]["ineligibility_reasons"])

    def test_no_conflict_when_states_agree(self):
        """AC-49: one timestamp missing, rows agree: the valid timestamp wins, no conflict."""
        out = self.run_rows_ts([("1111222233334444", "da", ""), ("1111222233334444", "da", "2026-01-01")])
        self.assertEqual(out.canonical[0]["source_record_number"], "2")
        self.assertEqual(out.canonical[0]["ineligibility_reasons"], "")

    def test_three_rows_one_winner(self):
        """AC-50: the same card three times: one winner, two losing rows."""
        out = self.run_rows_ts([("1111222233334444", "da", d) for d in ("2026-01-01", "2026-03-01", "2026-02-01")])
        self.assertEqual((len(out.canonical), len(out.duplicates)), (1, 2))
        self.assertEqual(out.canonical[0]["source_record_number"], "2")
        self.assertEqual({d.kept_record for d in out.duplicates}, {2})

    def test_rejected_cards_and_totals(self):
        """AC-27, AC-53 and Review Focus 4: rejected cards never reach the canonical table; totals reconcile."""
        out = self.run_rows([("", "da", "activ", "a@b.ro"), ("123", "da", "activ", "a@b.ro"),
                             ("1111222233334444", "da", "activ", "a@b.ro"), ("1111222233334444", "da", "activ", "a@b.ro")])
        self.assertEqual([r.codes for r in out.rejected], [["CARD_EMPTY"], ["CARD_INVALID"]])
        self.assertEqual(len(out.canonical) + len(out.rejected) + len(out.duplicates), 4)

    def test_all_cards_empty(self):
        """Review Focus 4: every card empty: every row rejected, nothing canonical."""
        out = self.run_rows([("", "da", "activ", "a@b.ro")] * 3)
        self.assertEqual((len(out.canonical), len(out.rejected)), (0, 3))

    def test_control_character_in_pass_through(self):
        """AC-25: a control character in a pass-through value is removed with a warning naming the column."""
        records = [RawRecord(1, 2, ["1111222233334444", "da", "activ", "a@b.ro", "", "2026-01-01", "Orto\x01dox"], "")]
        out = self.process(HEADER, records)
        self.assertEqual(out.canonical[0]["Religie"], "Ortodox")
        self.assertIn((1, "Religie", "CONTROL_CHARACTER_REMOVED"), [(w.record, w.field, w.code) for w in out.warnings])


DEFAULTS = {"missing_contact_pct": 3, "rejection_pct": 10, "memory_warn_pct": 50, "memory_stop_pct": 80}


def outcome(canonical, without_contact=0, rejected=0):
    rows = [{"ineligibility_reasons": "NO_CONTACT_CHANNEL" if i < without_contact else ""} for i in range(canonical)]
    return Outcome(rows, [Rejected(i, ["CARD_EMPTY"], "") for i in range(rejected)], [], [])


class ThresholdTests(unittest.TestCase):
    def codes(self, out, received):
        return [w.code for w in run_flags(out, received, DEFAULTS)]

    def test_missing_contact_threshold(self):
        """AC-51: above 3% of canonical customers without a channel: MISSING_CONTACT_THRESHOLD; at 3%: none."""
        self.assertIn("MISSING_CONTACT_THRESHOLD", self.codes(outcome(100, without_contact=4), 100))
        self.assertNotIn("MISSING_CONTACT_THRESHOLD", self.codes(outcome(100, without_contact=3), 100))

    def test_rejection_rate(self):
        """AC-52: more than 10% of received rows rejected: REJECTION_RATE_HIGH; the run is not stopped."""
        self.assertIn("REJECTION_RATE_HIGH", self.codes(outcome(89, rejected=11), 100))
        self.assertNotIn("REJECTION_RATE_HIGH", self.codes(outcome(90, rejected=10), 100))

    def test_all_cards_empty_flags_rejection(self):
        """Review Focus 4: every row rejected gives REJECTION_RATE_HIGH and no division error."""
        self.assertIn("REJECTION_RATE_HIGH", self.codes(outcome(0, rejected=3), 3))


if __name__ == "__main__":
    unittest.main()
