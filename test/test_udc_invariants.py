"""Synthetic edge cases supplement, never replace, published-file acceptance."""

import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from test_udc_engine import fixture

from not1mm import fsutils
from not1mm.lib.database import DataBase
from not1mm.udc.engine import Engine
from not1mm.udc.export import import_adif
from not1mm.udc.model import UdcError, parse
from not1mm.udc.storage import (
    Catalog,
    create_journal,
    engine_for,
    insert_batch,
)


def variant(bundle, **rules):
    text = bundle.definition.original.decode("utf-8-sig")
    for key, value in rules.items():
        pattern = r"(?mi)^" + re.escape(key) + r"\s*=[^\r\n]*"
        if re.search(pattern, text):
            text = re.sub(pattern, key + " = " + str(value), text)
        else:
            text += "\n" + key + " = " + str(value) + "\n"
    return parse(text.encode())


class Invariants(unittest.TestCase):
    def setUp(self):
        self.bundle, self.station, self.settings, self.contacts = fixture("RTC")
        self.engine = self.bundle.engine(self.station, self.settings)

    def engine_with(self, **rules):
        return Engine(
            variant(self.bundle, **rules),
            self.bundle.resources,
            self.station,
            self.settings,
            self.engine.geo,
        )

    def test_independent_tour_resets(self):
        for serial in (0, 1):
            for mult in (0, 1):
                e = self.engine_with(
                    MultipleSessions="1600/30",
                    ResetSNEverySession=serial,
                    ResetMultsEverySession=mult,
                )
                a = self.contacts[0]
                b = dict(a, ID="new", TS="2027-04-02 16:30:00")
                r = e.evaluate([a, b])
                self.assertEqual(r.multipliers, (1 + mult, 0, 0))
                self.assertEqual(
                    e.next_serial([dict(a, SentNr=9)], b["TS"], 3500),
                    1 if serial else 10,
                )

    def test_interval_and_mode_duplicates(self):
        e = self.engine_with(DupeQSOMinutesAgo=10, DupeType=3)
        a = self.contacts[0]
        b = dict(a, ID="b", TS="2027-04-02 16:09:59")
        c = dict(a, ID="c", TS="2027-04-02 16:10:00")
        d = dict(a, ID="d", TS="2027-04-02 16:10:01", Mode="SSB")
        self.assertEqual(
            [q["_dupe"] for q in e.evaluate([a, b, c, d]).contacts],
            [False, True, False, False],
        )

    def test_bonus_and_mode_band_factors(self):
        e = self.engine_with(
            PointsPerContact=2, BonusPoints="R3AAA, +5", PointsMultByBand="3.5, 3"
        )
        self.assertEqual(e.evaluate([self.contacts[0]]).points, 11)
        e = self.engine_with(
            PointsPerContact=2, BonusPoints="R3AAA, 5", PointsMultByMode="CW, 4"
        )
        self.assertEqual(e.evaluate([self.contacts[0]]).points, 5)

    def test_bom_and_explicit_legacy_encoding(self):
        text = self.bundle.definition.original.decode().replace(
            "RTC CONTEST", "Тест RTC"
        )
        for codec in ("utf-8-sig", "utf-16", "utf-32"):
            self.assertEqual(parse(text.encode(codec)).label, "Тест RTC")
        with self.assertRaises(UdcError):
            parse(text.encode("cp1251"))
        self.assertEqual(parse(text.encode("cp1251"), "cp1251").label, "Тест RTC")

    def test_no_sql_or_unknown_rule_execution(self):
        for key, value in [
            ("MultSqlString", "select * from dxlog"),
            ("UsesLASTEXCHmacro", "True"),
            ("StartOfContest", "0, 16"),
        ]:
            with self.subTest(key=key), self.assertRaises(UdcError):
                variant(self.bundle, **{key: value})
        with self.assertRaisesRegex(UdcError, "unknown selector"):
            self.engine_with(PointsPerContact="Mystery, 99")
        with self.assertRaises(UdcError):
            variant(self.bundle, BonusPoints2="5, ../../secret.txt")

    def test_adif_standard_compound_exchange(self):
        text = "<EOH><CALL:5>DL1AA<MODE:2>CW<FREQ:3>3.5<QSO_DATE:8>20270402<TIME_ON:6>160000<STX:1>1<SRX_STRING:7>17 JO62<EOR>"
        q = import_adif(self.engine, text)[0]
        self.assertEqual((q["NR"], q["GridSquare"]), ("17", "JO62"))
        with self.assertRaises(UdcError):
            import_adif(
                self.engine,
                text.replace("17 JO62", "17 JO62 X").replace("STRING:7", "STRING:9"),
            )

    def test_migration_preserves_old_contacts_and_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = DataBase(root / "logs.db", fsutils.APP_DATA_PATH, 1)
            db.add_contest(dict(self.settings, ContestName="general_logging"))
            q = dict(db.empty_contact, **self.contacts[0])
            db.log_contact(q)
            before = db.fetch_all_contacts_asc()
            create_journal(
                db, dict(self.settings, ContestNR=2), self.bundle, self.station
            )
            self.assertEqual(db.fetch_all_contacts_asc(), before)
            backup = next(root.glob("*.bak"))
            with sqlite3.connect(backup) as saved:
                self.assertIsNone(
                    saved.execute(
                        "SELECT 1 FROM sqlite_master WHERE name='UdcJournal'"
                    ).fetchone()
                )
                self.assertEqual(
                    saved.execute("SELECT count(*) FROM DXLOG").fetchone()[0], 1
                )
            # Same call and timestamp, independent journal, is valid.
            db.log_contact(dict(q, ContestNR=2, ID="second"))
            self.assertEqual(db.exec_sql("SELECT count(*) AS n FROM DXLOG")["n"], 2)
            db.conn.close()

    def test_snapshot_update_delete_and_isolation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = DataBase(root / "logs.db", fsutils.APP_DATA_PATH, 1)
            create_journal(db, self.settings, self.bundle, self.station)
            self.assertEqual(db.fetch_all_contacts_asc(), [])
            catalog = Catalog(root / "catalog")
            catalog.install(self.bundle)
            revision = variant(
                self.bundle, DisplayName="A different display name", PointsPerContact=99
            )
            from not1mm.udc.storage import Bundle

            updated = Bundle(
                self.bundle.filename,
                revision,
                self.bundle.resources,
                self.bundle.geography_name,
            )
            catalog.install(updated)
            self.assertEqual(
                updated.definition.identifier, self.bundle.definition.identifier
            )
            create_journal(db, dict(self.settings, ContestNR=2), updated, self.station)
            a = dict(db.empty_contact, **self.contacts[0])
            db.log_contact(a)
            b = dict(a, ID="foreign", ContestNR=2)
            db.log_contact(b)
            self.assertEqual(
                db.exec_sql("SELECT Points FROM DXLOG WHERE ContestNR=1")["Points"], 1
            )
            self.assertEqual(
                db.exec_sql("SELECT Points FROM DXLOG WHERE ContestNR=2")["Points"], 99
            )
            changed = dict(a, GridSquare="BAD")
            with self.assertRaises(UdcError):
                db.change_contact(changed)
            self.assertEqual(db.fetch_all_contacts_asc()[0]["GridSquare"], "KO85")
            # Editing section/locator must remove the old multiplier, not retain it.
            db.change_contact(dict(a, GridSquare="JO62"))
            self.assertEqual(
                engine_for(db, 1).evaluate(db.fetch_all_contacts_asc()).multipliers,
                (1, 0, 0),
            )
            # Bad ADIF batch rolls back both new rows and derived point changes.
            before = db.fetch_all_contacts_asc()
            with self.assertRaises((sqlite3.IntegrityError, UdcError)):
                insert_batch(db, [dict(a, ID="collision"), dict(a, ID="collision")])
            self.assertEqual(db.fetch_all_contacts_asc(), before)
            # Identical geography blobs are deduplicated across revisions.
            count = db.exec_sql("SELECT count(*) AS n FROM UdcResource")["n"]
            self.assertEqual(count, 3)
            import shutil

            shutil.rmtree(root / "catalog")
            db.conn.close()
            db = DataBase(root / "logs.db", fsutils.APP_DATA_PATH, 1)
            self.assertEqual(engine_for(db, 1).d.label, "RTC CONTEST")
            self.assertEqual(engine_for(db, 2).d.label, "A different display name")
            db.delete_contact(a["ID"])
            self.assertEqual(
                db.exec_sql("SELECT Points FROM DXLOG WHERE ContestNR=2")["Points"], 99
            )
            db.conn.close()
