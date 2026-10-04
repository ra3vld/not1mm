"""Offline real-file tests. Expectations below are handwritten arithmetic."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from udc_corpus import corpus_root, require_corpus

from not1mm import fsutils
from not1mm.lib.database import DataBase
from not1mm.udc.export import adif, cabrillo, import_adif
from not1mm.udc.model import UdcError, parse
from not1mm.udc.storage import Catalog, Snapshots, engine_for, read_bundle

MANIFESTS = Path(__file__).parent / "fixtures" / "udc"
FIXTURES = corpus_root()


def require_fixtures():
    """Only external-corpus checks are optional on a clean checkout."""
    try:
        return require_corpus()
    except FileNotFoundError as error:
        raise unittest.SkipTest(str(error)) from error


CASES = {
    "VLADIMIR": (
        "VLADIMIR/VLADIMIR.udc",
        "RA3VLD",
        "# KO85",
        None,
        "CW",
        [
            ("R3AAA", 3500, "VL01", 1),
            ("R3AAA", 3500, "VL01", 0),
            ("DL1AAA", 3500, "KO85", 1),
            ("K1AAA", 3500, "KO86", 1),
            ("DL1AAA", 1800, "KO86", 1),
            ("R3AAA", 3500, "VL01", 1, "SSB"),
            ("R3AAB", 3500, "VL02", 1),
            ("R3AAA", 3500, "VL01", 1, "CW", "16:30:00"),
        ],
        35,
        (5, 0, 0),
    ),
    "RTC": (
        "RTC/RTC.udc",
        "RA3VLD",
        "# KO85",
        None,
        "CW",
        [
            ("R3AAA", 3500, "KO85", 1),
            ("R3AAA", 3500, "KO85", 0),
            ("DL1AAA", 3500, "JO62", 1),
            ("K1AAA", 3500, "FN31", 3),
            ("DL1AAA", 7000, "JO62", 1),
            ("R3AAA", 3500, "KO85", 0, "SSB"),
        ],
        24,
        (4, 0, 0),
    ),
    "KCJ_DX": (
        "KCJ_DX/KCJ_DX.udc",
        "RA3VLD",
        "16",
        None,
        "CW",
        [
            ("JA1AAA", 3500, "TK", 2),
            ("JA1AAA", 3500, "TK", 0),
            ("JA2AAA", 3500, "CB", 2),
            ("DL1AAA", 3500, "14", 1),
            ("JA1AAA", 7000, "TK", 2),
        ],
        21,
        (3, 0, 0),
    ),
    "KCJ_JA": (
        "KCJ_JA/KCJ_JA.udc",
        "JA1ZZZ",
        "TK",
        None,
        "CW",
        [
            ("JA1AAA", 3500, "TK", 1),
            ("DL1AAA", 3500, "14", 2),
            ("HL1AAA", 3500, "25", 2),
            ("JA2AAA", 3500, "CB", 1),
            ("JA1AAA", 3500, "TK", 0),
            ("JA1AAA", 7000, "TK", 1),
        ],
        35,
        (3, 1, 1),
    ),
    "TRHFSSB_DX": (
        "TRHFSSB/TRHFSSB_DX.udc",
        "DL1ZZZ",
        "#",
        None,
        "SSB",
        [
            ("TA1AAA", 3500, "34", 20),
            ("DL1AAA", 14000, "", 3),
            ("K1AAA", 14000, "", 5),
            ("TA2AAA", 14000, "06", 10),
            ("TA2AAA", 14000, "06", 0),
        ],
        228,
        (2, 4, 0),
    ),
    "TRHFSSB_TA": (
        "TRHFSSB/TRHFSSB_TA.udc",
        "TA1ZZZ",
        "34",
        None,
        "SSB",
        [
            ("TA1AAA", 3500, "06", 4),
            ("DL1AAA", 14000, "", 5),
            ("K1AAA", 14000, "", 10),
            ("TA1AAA", 3500, "06", 0),
        ],
        76,
        (1, 3, 0),
    ),
    "SLTESTEN": (
        "SLTESTEN/SL-TESTEN.udc",
        "DL1ZZZ",
        "# JN58",
        "SLTESTEN/SL_cty.dat",
        "CW",
        [
            ("SL1AAA", 3500, "JO99", 5),
            ("SM1AAA", 3500, "JO88", 1),
            ("SL1AAA", 3500, "JO99", 0),
            ("SL1AAA", 7000, "JO99", 5),
            ("SL1AAA", 3500, "JO99", 0, "SSB"),
        ],
        33,
        (3, 0, 0),
    ),
    "URCDXRY": (
        "URCDXRY/URC-DX-RY.udc",
        "DL1ZZZ",
        "BER",
        None,
        "RTTY",
        [
            ("R3AAA", 14000, "MOS", 2),
            ("K1AAA", 14000, "TXS", 4),
            ("DL1AAA", 14000, "BER", 1),
            ("R3AAA", 7000, "MOS", 2),
            ("UA3AAA/MM", 3500, "MOS", 3),
            ("R3AAA", 14000, "MOS", 0),
        ],
        60,
        (5, 0, 0),
    ),
}


def fixture(name):
    require_fixtures()
    path, call, sent, geo, md, qsos, _score, _mults = CASES[name]
    bundle = read_bundle(
        FIXTURES / path,
        extra=[FIXTURES / "kcj/kcj.sec", FIXTURES / "VLADIMIR/RDACR3V.sec"],
        geo=FIXTURES / geo if geo else FIXTURES / "geography/cty.json",
    )
    station = {"Call": call, "GridSquare": "KO85" if call == "RA3VLD" else "JN58"}
    settings = {
        "ContestNR": 1,
        "ContestName": bundle.definition.identifier,
        "SentExchange": sent,
        "StartDate": "2027-04-02 16:00:00",
        "ModeCategory": "SSB+CW" if bundle.definition.get("mode") == "BOTH" else md,
        "OperatorCategory": "SINGLE-OP",
    }
    contacts = []
    for i, row in enumerate(qsos):
        call, freq, exchange, _points, *qmode = row
        q = {
            "TS": f"2027-04-02 16:00:{i:02}",
            "ID": f"{i:032}",
            "Call": call,
            "Freq": freq,
            "Mode": qmode[0] if qmode else md,
            "ContestNR": 1,
            "SNT": "599",
            "RCV": "599",
            "SentNr": i + 1,
            "NR": 10 + i,
            "Exchange1": exchange,
            "GridSquare": exchange if name in ("RTC", "SLTESTEN") else "",
        }
        if len(qmode) > 1:
            q["TS"] = "2027-04-02 " + qmode[1]
        contacts.append(q)
    return bundle, station, settings, contacts


class PublishedContests(unittest.TestCase):
    def setUp(self):
        require_fixtures()

    def test_original_hashes(self):
        for entry in json.loads((MANIFESTS / "provenance.json").read_text()):
            for filename, sha in entry["files"].items():
                self.assertEqual(
                    hashlib.sha256((FIXTURES / filename).read_bytes()).hexdigest(), sha
                )

    def test_hand_calculated_scores_and_exports(self):
        for name, case in CASES.items():
            with self.subTest(name=name):
                bundle, station, settings, contacts = fixture(name)
                engine = bundle.engine(station, settings)
                result = engine.evaluate(contacts)
                self.assertEqual(
                    [q["Points"] for q in result.contacts], [q[3] for q in case[5]]
                )
                self.assertEqual(result.multipliers, case[7])
                self.assertEqual(result.score, case[6])
                text = cabrillo(engine, contacts)
                self.assertEqual(text.count("QSO:"), len(contacts))
                self.assertIn(f"CLAIMED-SCORE: {case[6]}", text)
                imported = import_adif(engine, adif(engine, contacts))
                self.assertEqual(engine.evaluate(imported).score, case[6])
                for old, new in zip(contacts, imported):
                    for col in (
                        "Call",
                        "Freq",
                        "Exchange1",
                        "GridSquare",
                        "NR",
                        "SentNr",
                    ):
                        self.assertEqual(
                            str(old[col]),
                            str(new[col]) if col != "Freq" else str(int(new[col])),
                        )

    def test_catalog_snapshot_and_mutations(self):
        for name in CASES:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                bundle, station, settings, contacts = fixture(name)
                catalog = Catalog(root / "catalog")
                ident = catalog.install(bundle)
                self.assertIn((ident, bundle.definition.label), catalog.entries())
                db = DataBase(root / "test.db", fsutils.APP_DATA_PATH, 1)
                db.add_contest(settings)
                Snapshots(db.conn).create(1, bundle, station)
                self.assertEqual(len(list(root.glob("*.bak"))), 1)
                for contact in contacts:
                    db.log_contact(contact)
                result = engine_for(db, 1).evaluate(db.fetch_all_contacts_asc())
                self.assertEqual(result.score, CASES[name][6])
                changed = dict(db.fetch_all_contacts_asc()[0], Call="DL9ZZZ")
                db.change_contact(changed)
                expected = engine_for(db, 1).evaluate(db.fetch_all_contacts_asc())
                self.assertEqual(
                    [q["Points"] for q in db.fetch_all_contacts_asc()],
                    [q["Points"] for q in expected.contacts],
                )
                db.delete_contact(changed["ID"])
                import shutil

                shutil.rmtree(root / "catalog")
                db.conn.close()
                db = DataBase(root / "test.db", fsutils.APP_DATA_PATH, 1)
                engine = engine_for(db, 1)
                rows = db.fetch_all_contacts_asc()
                self.assertIn("END-OF-LOG:", cabrillo(engine, rows))
                self.assertEqual(
                    len(import_adif(engine, adif(engine, rows))), len(rows)
                )
                db.conn.close()

    def test_missing_dependencies_and_unsupported_rules(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "KCJ.udc"
            p.write_bytes((FIXTURES / "KCJ_DX/KCJ_DX.udc").read_bytes())
            with self.assertRaisesRegex(UdcError, "Missing dependency: KCJ.sec"):
                read_bundle(p)
        original = (FIXTURES / "RTC/RTC.udc").read_bytes()
        with self.assertRaisesRegex(UdcError, "active rule"):
            parse(original.replace(b"UsesLASTEXCHmacro =", b"UsesLASTEXCHmacro =True"))
        with self.assertRaises(UdcError):
            parse(
                original.replace(
                    b"MultSqlString = GRID", b"MultSqlString = DROP TABLE DXLOG"
                )
            )

    def test_sessions_and_separate_resets(self):
        b, station, settings, contacts = fixture("RTC")
        raw = b.definition.original
        raw = raw.replace(b"MultipleSessions = ", b"MultipleSessions = 1600/30")
        d = parse(raw)
        engine = type(b.engine(station, settings))(
            d, b.resources, station, settings, b.engine(station, settings).geo
        )
        a = contacts[0]
        before = dict(a, ID="b", TS="2027-04-02 16:29:59", SentNr=2)
        after = dict(a, ID="c", TS="2027-04-02 16:30:00", SentNr=3)
        r = engine.evaluate([a, before, after])
        self.assertEqual([q["Points"] for q in r.contacts], [1, 0, 1])
        self.assertEqual(r.multipliers, (1, 0, 0))
        self.assertEqual(engine.next_serial([a, before], after["TS"], 3500), 3)
        reset = parse(
            raw.replace(
                b"ResetMultsEverySession = ", b"ResetMultsEverySession = 1"
            ).replace(b"ResetSNEverySession =", b"ResetSNEverySession =1")
        )
        e = type(engine)(reset, b.resources, station, settings, engine.geo)
        self.assertEqual(e.evaluate([a, before, after]).multipliers, (2, 0, 0))
        self.assertEqual(e.next_serial([a, before], after["TS"], 3500), 1)


if __name__ == "__main__":
    unittest.main()
