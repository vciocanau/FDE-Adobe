"""Regression tests for the findings of the final whole-branch review."""
import contextlib
import csv
import io
import json
import shutil
from pathlib import Path

from ingest.cli import main
from ingest.fields import parse_timestamp
from ingest.mapping import load_dictionary, resolve_mapping
from ingest.reader import read_file
from tests.helpers import TempDirTestCase
from tests.test_agent import NOW, RecordingAgent
from tests.test_cli import DICTIONARY
from tests.test_fields import RUN


class CliCase(TempDirTestCase):
    """Helpers only, no tests: runs the command line on a small input written for the test."""

    def setUp(self):
        super().setUp()
        self.out = self.tmp / "runs"
        self.dictionary = self.tmp / "synonyms.json"
        shutil.copy(DICTIONARY, self.dictionary)

    def run_cli(self, text: str, *extra):
        path = self.write(text.encode())
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = main(["run", "--input", str(path), "--output", str(self.out), "--dictionary", str(self.dictionary), *extra])
        return code, err.getvalue()

    def canonical(self):
        folder = next(self.out.glob("run_*"))
        with open(folder / "canonical_customers.csv", newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        return rows[0], [dict(zip(rows[0], r)) for r in rows[1:]]


class ReviewFixTests(CliCase):
    def test_input_column_named_like_an_output_column(self):
        """Spec 7.3 and 8 (review C1): an input column eligible_for_campaign never overwrites the computed value."""
        code, err = self.run_cli("card_number,consent,subscription,email,eligible_for_campaign\n"
                                 "1111222233334444,nu,inactiv,a@b.ro,yes\n")
        self.assertEqual(code, 0, err)
        header, rows = self.canonical()
        self.assertEqual(len(header), len(set(header)))
        self.assertEqual(rows[0]["eligible_for_campaign"], "no")
        self.assertEqual(rows[0]["eligible_for_campaign_2"], "yes")

    def test_suffix_never_collides(self):
        """Spec 4 (review I1): duplicate unknown names get suffixes that never collide; no value is lost."""
        code, err = self.run_cli("card_number,X,X,X_2\n1111222233334444,a,b,c\n")
        self.assertEqual(code, 0, err)
        header, rows = self.canonical()
        self.assertEqual(len(header), len(set(header)))
        self.assertEqual(sorted(rows[0][h] for h in header if h.startswith("X")), ["a", "b", "c"])

    def test_bad_quoting_does_not_create_fake_customers(self):
        """Spec 4 Quoting (review I2): a quoted field after a bad quote is part of the rejected record."""
        r = read_file(self.write(b'card_number,first_name,note\n1111222233334444,"Ana"x,"line one\n2222333344445555,Fake,row"\n3333444455556666,Ion,ok\n'))
        self.assertEqual([rec.cells[1] for rec in r.records], ["Ion"])
        self.assertEqual(r.rejected[0].codes, ["BAD_QUOTING"])
        self.assertEqual(r.rejected[0].original, '1111222233334444,"Ana"x,"line one\n2222333344445555,Fake,row"')
        self.assertEqual(r.rows_received, 2)

    def test_malformed_offset_is_unreadable(self):
        """Spec 6.6 step 4 (review I3): a malformed time-zone offset empties the field, it never stops the run."""
        for raw in ["2026-01-01T10:00+24:00", "2026-01-01T10:00-99:00", "2026-01-01T10:00+01:99"]:
            self.assertEqual(parse_timestamp(raw, RUN).codes, ["TIMESTAMP_UNREADABLE"], raw)

    def test_rejected_approval_is_not_saved(self):
        """Spec 5 (review I4): an approval that ends in FIELD_MAPPED_TWICE is not saved in the dictionary."""
        header = ["card", "Mob", "email"]
        with self.assertRaises(Exception):
            resolve_mapping(header, [["x"] * 3], self.dictionary, self.out, "crm.csv",
                            RecordingAgent({"Mob": ("phone", 75, "mobile")}), None, NOW)
        path = next((self.out / "mapping_proposals").glob("*.json"))
        data = json.loads(path.read_text())
        data["proposals"][0].update(decision="change", use_field="email")
        path.write_text(json.dumps(data))
        with self.assertRaises(Exception) as e:
            resolve_mapping(header, [["x"] * 3], self.dictionary, self.out, "crm.csv", RecordingAgent(), path, NOW)
        self.assertEqual(e.exception.code, "FIELD_MAPPED_TWICE")
        self.assertNotIn("Mob", load_dictionary(self.dictionary)["email"])

    def test_logs_folder_is_a_file(self):
        """Spec 9 (review M3): when the log cannot be created the operator gets one line, no traceback."""
        self.out.mkdir()
        (self.out / "logs").write_text("x")
        code, err = self.run_cli("card_number,email\n1111222233334444,a@b.ro\n")
        self.assertEqual(code, 2)
        self.assertIn("ERROR OUTPUT_NOT_WRITABLE", err)
        self.assertNotIn("Traceback", err)

    def test_log_has_no_column_names(self):
        """Spec 10.1 step 4 (review M4): column names, which may be personal data, never reach the log."""
        code, err = self.run_cli("card_number,ion@x.ro,0722123456\n1111222233334444,a,b\n")
        self.assertEqual(code, 0, err)
        log = next((self.out / "logs").glob("*.log")).read_text()
        self.assertNotIn("ion@x.ro", log)
        self.assertNotIn("0722123456", log)


class CoverageTests(CliCase):
    """Review I5: acceptance cases whose first tests proved only part of the expected result."""

    def test_ac25_control_characters_in_every_field(self):
        """AC-25: a control character in email, phone, consent, subscription and app installed is removed;
        the rest follows the field's rule; written files stay valid."""
        code, err = self.run_cli("card_number,email,phone,consent,subscription,app_installed\n"
                                 "1111222233334444,a@b\x01.ro,0722\x02123456,d\x03a,activ\x04,da\x05\n")
        self.assertEqual(code, 0, err)
        _, rows = self.canonical()
        r = rows[0]
        self.assertEqual((r["email"], r["phone"], r["consent"], r["subscription"], r["app_installed"]),
                         ("a@b.ro", "+40722123456", "yes", "active", "yes"))
        folder = next(self.out.glob("run_*"))
        with open(folder / "warnings.csv", newline="", encoding="utf-8") as f:
            fields = sorted(w["field"] for w in csv.DictReader(f) if w["code"] == "CONTROL_CHARACTER_REMOVED")
        self.assertEqual(fields, ["app_installed", "consent", "email", "phone", "subscription"])
        for name in ("canonical_customers.csv", "warnings.csv", "rejected_rows.csv"):
            self.assertNotRegex((folder / name).read_text(encoding="utf-8"), "[\x00-\x08\x0b\x0c\x0e-\x1f]")

    def test_ac11_short_row_rules(self):
        """AC-11: a short row with no card cell is rejected with CARD_EMPTY; a short row without consent is unknown."""
        code, err = self.run_cli("email,consent,card_number\na@b.ro\nc@d.ro,da,1111222233334444\nx@y.ro,da\n")
        self.assertEqual(code, 0, err)
        summary = json.loads(next(self.out.glob("run_*/run_summary.json")).read_text())
        self.assertEqual(summary["destinations"], {"canonical": 1, "rejected": 2, "duplicate_losing": 0, "reconciled": True})

    def test_ac11_missing_consent_is_unknown(self):
        """AC-11: a short row whose consent cell is missing gets consent unknown and is not eligible."""
        code, err = self.run_cli("card_number,email,subscription,consent\n1111222233334444,a@b.ro,activ\n")
        self.assertEqual(code, 0, err)
        _, rows = self.canonical()
        self.assertEqual((rows[0]["consent"], rows[0]["eligible_for_campaign"]), ("unknown", "no"))

    def test_ac42_all_outputs_published(self):
        """AC-42: without a consent column all five outputs are still published."""
        code, err = self.run_cli("card_number,email,subscription\n1111222233334444,a@b.ro,activ\n")
        self.assertEqual(code, 0, err)
        folder = next(self.out.glob("run_*"))
        self.assertEqual(len(list(folder.iterdir())), 5)
        self.assertIn("CONSENT_COLUMN_MISSING", (folder / "warnings.csv").read_text())

    def test_ac51_counts_in_summary(self):
        """AC-51: the missing-contact share and its flag are in the summary."""
        code, err = self.run_cli("card_number,consent,subscription,email\n1111222233334444,da,activ,\n"
                                 "1111222233335555,da,activ,a@b.ro\n")
        self.assertEqual(code, 0, err)
        summary = json.loads(next(self.out.glob("run_*/run_summary.json")).read_text())
        self.assertEqual(summary["observed"]["missing_contact_pct"], 50.0)
        self.assertTrue(summary["flags"]["source_probably_broke"])
        self.assertEqual(summary["eligibility"]["reasons"]["NO_CONTACT_CHANNEL"], 1)

    def test_ac63_log_remains_after_failure(self):
        """AC-63: after a failed run the log remains and names the stage."""
        from unittest import mock
        with mock.patch("ingest.writer.write_duplicates", side_effect=OSError("disk full")):
            code, err = self.run_cli("card_number,email\n1111222233334444,a@b.ro\n")
        self.assertEqual(code, 2)
        log = next((self.out / "logs").glob("*.log")).read_text()
        self.assertIn("ERROR write OUTPUT_NOT_WRITABLE", log)

    def test_ac66_permissions_skipped_in_log(self):
        """AC-66: on a system without POSIX permissions PERMISSIONS_SKIPPED is in the log."""
        from unittest import mock
        with mock.patch("ingest.publish._posix", return_value=False):
            code, err = self.run_cli("card_number,email\n1111222233334444,a@b.ro\n")
        self.assertEqual(code, 0, err)
        self.assertIn("PERMISSIONS_SKIPPED", next((self.out / "logs").glob("*.log")).read_text())

    def test_ac37_ac38_every_listed_value(self):
        """AC-37 and AC-38: every listed value, in upper case and with spaces, maps as listed."""
        from ingest import fields
        for values, func, expected in [(fields.CONSENT_YES, fields.clean_consent, "yes"),
                                       (fields.CONSENT_NO, fields.clean_consent, "no"),
                                       (fields.SUBSCRIPTION_ACTIVE, fields.clean_subscription, "active"),
                                       (fields.SUBSCRIPTION_INACTIVE, fields.clean_subscription, "inactive")]:
            for value in values:
                self.assertEqual(func(f"  {value.upper()} ").value, expected, value)


class ExternalReviewTests(CliCase):
    """Findings of an external review of the published branch."""

    def test_threshold_decision_is_the_same_in_csv_and_json(self):
        """AC-51: 30 of 999 customers without contact (3.003%) is above 3% in warnings.csv and in the summary."""
        rows = ["card_number,consent,subscription,email"]
        for i in range(999):
            rows.append(f"{1000000000000000 + i},da,activ,{'' if i < 30 else 'a@b.ro'}")
        code, err = self.run_cli("\n".join(rows) + "\n")
        self.assertEqual(code, 0, err)
        folder = next(self.out.glob("run_*"))
        self.assertIn("MISSING_CONTACT_THRESHOLD", (folder / "warnings.csv").read_text())
        summary = json.loads((folder / "run_summary.json").read_text())
        self.assertTrue(summary["flags"]["source_probably_broke"])

    def test_rejection_decision_is_the_same_in_csv_and_json(self):
        """AC-52: the rejection flag in the summary follows the same decision as the warning."""
        rows = ["card_number,email"] + [f"{1000000000000000 + i},a@b.ro" for i in range(899)] + [",x"] * 101
        code, err = self.run_cli("\n".join(rows) + "\n")
        folder = next(self.out.glob("run_*"))
        in_csv = "REJECTION_RATE_HIGH" in (folder / "warnings.csv").read_text()
        self.assertEqual(json.loads((folder / "run_summary.json").read_text())["flags"]["rejection_rate_high"], in_csv)
        self.assertTrue(in_csv)

    def test_two_runs_in_the_same_second_keep_their_own_folders(self):
        """Spec 8 and D17: a run that fails never deletes another run's temporary folder."""
        from unittest import mock
        from datetime import datetime, timezone
        fixed = datetime(2026, 11, 5, 8, 33, tzinfo=timezone.utc)
        self.out.mkdir()
        other = self.out / ".tmp_run_2026-11-05_083300Z"
        other.mkdir()
        (other / "canonical_customers.csv").write_text("other run")
        with mock.patch("ingest.cli.datetime") as dt:
            dt.now.return_value = fixed
            dt.fromtimestamp = datetime.fromtimestamp
            code, err = self.run_cli("card_number,email\n1111222233334444,a@b.ro\n")
        self.assertEqual(code, 0, err)
        self.assertEqual((other / "canonical_customers.csv").read_text(), "other run")

    def test_temporary_folder_is_private_before_any_write(self):
        """Spec 8 (D26): the temporary folder is owner-only from the moment it is created."""
        import os
        import stat
        from unittest import mock
        if os.name != "posix":
            self.skipTest("POSIX only")
        seen = []
        real = __import__("ingest.writer", fromlist=["write_canonical"]).write_canonical

        def spy(temp, *args, **kwargs):
            seen.append(stat.S_IMODE(temp.stat().st_mode))
            return real(temp, *args, **kwargs)

        with mock.patch("ingest.writer.write_canonical", side_effect=spy):
            code, err = self.run_cli("card_number,email\n1111222233334444,a@b.ro\n")
        self.assertEqual(code, 0, err)
        self.assertEqual(seen, [0o700])


class MissingOptionalColumnTests(CliCase):
    """Spec 4 (Fields: absent optional columns give empty values) combined with spec 7.2 (duplicates)."""

    def test_duplicates_without_a_timestamp_column(self):
        """AC-44: with no last_interaction_at column, a duplicated card resolves like missing timestamps."""
        code, err = self.run_cli("card_number,email,consent,subscription\n"
                                 "1000200030004000,one@example.com,da,activ\n"
                                 "1000200030004000,two@example.com,da,activ\n")
        self.assertEqual(code, 0, err)
        folder = next(self.out.glob("run_*"))
        _, rows = self.canonical()
        self.assertEqual([(r["email"], r["source_record_number"]) for r in rows], [("two@example.com", "2")])
        self.assertIn("LOST_TIE_LATER_ROW_WINS", (folder / "duplicates.csv").read_text())
        self.assertIn("DUPLICATE_TIE", (folder / "warnings.csv").read_text())

    def test_any_missing_optional_column_with_duplicates(self):
        """Spec 4 and 7.2: every optional column may be absent while a card is duplicated; the run never fails."""
        optional = ["first_name", "last_name", "email", "phone", "app_installed",
                    "last_interaction_at", "last_purchase_at", "last_purchase_amount"]
        values = {"card_number": "1000200030004000", "first_name": "Ana", "last_name": "Pop", "email": "a@b.ro",
                  "phone": "0722123456", "app_installed": "da", "consent": "da", "subscription": "activ",
                  "last_interaction_at": "2026-10-01", "last_purchase_at": "2026-09-01", "last_purchase_amount": "12.50"}
        for missing in optional:
            with self.subTest(missing=missing):
                shutil.rmtree(self.out, ignore_errors=True)
                header = [c for c in values if c != missing]
                row = ",".join(values[c] for c in header)
                code, err = self.run_cli(",".join(header) + "\n" + row + "\n" + row + "\n")
                self.assertEqual(code, 0, err)
                summary = json.loads(next(self.out.glob("run_*/run_summary.json")).read_text())
                self.assertEqual(summary["destinations"],
                                 {"canonical": 1, "rejected": 0, "duplicate_losing": 1, "reconciled": True})
