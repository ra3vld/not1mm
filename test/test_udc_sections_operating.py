"""Independent arithmetic for original Vladimir rules and new generic UDC options."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from test_udc_engine import FIXTURES, MANIFESTS, fixture
from test_udc_invariants import variant

from not1mm import fsutils
from not1mm.lib.database import DataBase
from not1mm.udc import ENGINE_VERSION
from not1mm.udc.engine import Engine
from not1mm.udc.export import adif, cabrillo, import_adif
from not1mm.udc.model import UdcError, weekly_time
from not1mm.udc.operating import off_times, schedule_window
from not1mm.udc.sections import parse_sections
from not1mm.udc.storage import (
    Bundle,
    Catalog,
    Snapshots,
    create_journal,
    engine_for,
    read_bundle,
)


class SectionsAndOperating(unittest.TestCase):
    def setUp(self):
        self.bundle, self.station, self.settings, self.contacts = fixture("VLADIMIR")
        self.engine = self.bundle.engine(self.station, self.settings)

    def test_unchanged_vladimir_originals(self):
        source = json.loads((MANIFESTS / "VLADIMIR/provenance.json").read_text())
        for name, data in source["files"].items():
            self.assertEqual(
                hashlib.sha256((FIXTURES / "VLADIMIR" / name).read_bytes()).hexdigest(),
                data["sha256"],
            )
        self.assertEqual(self.bundle.definition.get("startofcontest"), "5, 3")
        self.assertEqual(self.bundle.definition.start.describe(), "Wed 03:00 UTC")
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            self.bundle.export(output)
            for name in source["files"]:
                self.assertEqual(
                    (output / name).read_bytes(),
                    (FIXTURES / "VLADIMIR" / name).read_bytes(),
                )
        with tempfile.TemporaryDirectory() as temp:
            udc = Path(temp) / "VLADIMIR.udc"
            udc.write_bytes(self.bundle.definition.original)
            with self.assertRaisesRegex(UdcError, "Missing dependency: RDACR3V.sec"):
                read_bundle(udc)

    def test_aliases_keep_received_exchange_in_exports(self):
        contacts = [self.contacts[i] for i in (0, 2, 3)]
        result = self.engine.evaluate(contacts)
        self.assertEqual([q["Sect"] for q in result.contacts], ["VL01", "KO", "KO"])
        self.assertEqual(
            [q["Exchange1"] for q in result.contacts], ["VL01", "KO85", "KO86"]
        )
        self.assertEqual(
            (result.points, result.multipliers, result.score), (3, (2, 0, 0), 6)
        )
        self.assertIn("KO86", cabrillo(self.engine, contacts))
        restored = import_adif(self.engine, adif(self.engine, contacts))
        self.assertEqual(self.engine.evaluate(restored).score, 6)
        self.assertEqual([q["Exchange1"] for q in restored], ["VL01", "KO85", "KO86"])

    def test_section_alias_validation_and_filters(self):
        self.assertEqual(
            parse_sections(["KO85\tKO", "KO86,KO", "VL01", ";note"], "test.sec"),
            {"KO85": "KO", "KO86": "KO", "KO": "KO", "VL01": "VL01"},
        )
        for lines in (
            ["KO85\tKO", "KO85\tJO"],
            ["A\tB\tC"],
            [";empty"],
            ["A\tselect *"],
        ):
            with self.subTest(lines=lines), self.assertRaises(UdcError):
                parse_sections(lines, "test.sec")
        definition = variant(self.bundle, CountMultOnlyForSec="KO")
        e = Engine(
            definition,
            self.bundle.resources,
            self.station,
            self.settings,
            self.engine.geo,
        )
        self.assertEqual(
            e.evaluate([self.contacts[i] for i in (0, 2, 3)]).multipliers, (1, 0, 0)
        )
        definition = variant(self.bundle, QsoErrorString="RDACR3V")
        e = Engine(
            definition,
            self.bundle.resources,
            self.station,
            self.settings,
            self.engine.geo,
        )
        e.normalize(self.contacts[2])
        with self.assertRaisesRegex(UdcError, "RDACR3V"):
            e.normalize(dict(self.contacts[2], Exchange1="ZZZZ"))

    def test_direct_section_field_and_own_compound_exchange(self):
        d = variant(
            self.bundle,
            EntryWindowInfo="SntNrText,500,RcvNrText,500,SectText,500",
            QsoErrorString="SectText_RDACR3V",
        )
        e = Engine(
            d, self.bundle.resources, self.station, self.settings, self.engine.geo
        )
        q = e.normalize(dict(self.contacts[2], Exchange1="", Sect="KO85"))
        self.assertEqual(q["Sect"], "KO")
        d = variant(self.bundle, DoNotCountMeAsMult=True)
        e = Engine(
            d, self.bundle.resources, self.station, self.settings, self.engine.geo
        )
        result = e.evaluate([self.contacts[i] for i in (0, 2, 3)])
        self.assertEqual((result.points, result.multipliers), (3, (1, 0, 0)))

    def test_tours_band_mode_and_global_number(self):
        a = self.contacts[0]
        rows = [
            a,
            dict(a, ID="before", TS="2027-04-02 16:29:59"),
            dict(a, ID="after", TS="2027-04-02 16:30:00", SentNr=3),
        ]
        result = self.engine.evaluate(rows)
        self.assertEqual([q["Points"] for q in result.contacts], [1, 0, 1])
        self.assertEqual(result.multipliers, (1, 0, 0))
        self.assertEqual(self.engine.next_serial(rows, "2027-04-02 17:00:00", 1800), 4)
        self.assertEqual(
            self.engine.evaluate(
                [a, dict(a, ID="phone", Mode="SSB"), dict(a, ID="160", Freq=1800)]
            ).multipliers,
            (3, 0, 0),
        )

    def test_multiplier_band_sets(self):
        bundle, station, settings, rows = fixture("RTC")
        for value, frequency, allowed in [
            (1, 3500, True),
            (1, 50000, False),
            (2, 10100, True),
            (3, 50000, True),
            (3, 70000, False),
            (4, 144000, True),
            (4, 3500, False),
        ]:
            d = variant(bundle, MultiplierBands=value, ShowWarcBands=True)
            e = Engine(d, bundle.resources, station, settings, self.engine.geo)
            result = e.evaluate([dict(rows[0], Freq=frequency)])
            self.assertEqual(result.multipliers[0], int(allowed), (value, frequency))
        for value in [0, 5, "1,2"]:
            with self.subTest(value=value), self.assertRaises(UdcError):
                variant(bundle, MultiplierBands=value)

    def test_weekly_calendar_validation(self):
        self.assertEqual(weekly_time("7,1.5", "StartOfContest").minutes, 90)
        self.assertEqual(weekly_time("1, 0", "StartOfContest").weekday, 5)
        for text in [
            "0,3",
            "8,3",
            "5,24",
            "5,-1",
            "5,nan",
            "5,inf",
            "5,0.001",
            "5,3,9",
        ]:
            with self.subTest(text=text), self.assertRaises(UdcError):
                weekly_time(text, "StartOfContest")
        d = variant(self.bundle, StartOfContest="7,16", EndOfContest="1,1.5")
        begin, end = schedule_window(d, "2027-04-02 16:00:00")
        self.assertEqual(
            (begin.strftime("%Y-%m-%d %H:%M"), end.strftime("%Y-%m-%d %H:%M")),
            ("2027-04-02 16:00", "2027-04-03 01:30"),
        )
        with self.assertRaisesRegex(UdcError, "explicit start and end"):
            self.engine.off_times(self.contacts)
        # Equal endpoints are ambiguous, not silently interpreted as a week.
        self.assertIsNone(
            schedule_window(self.bundle.definition, self.settings["StartDate"])[1]
        )

    def test_full_minute_off_time_edges_and_boundary(self):
        qsos = [
            {"TS": "2027-04-02 16:04:59"},
            {"TS": "2027-04-02 16:15:00"},
            {"TS": "2027-04-02 16:24:59"},
            {"TS": "2027-04-02 16:24:59"},
        ]
        result = off_times(qsos, "2027-04-02 16:00:00", "2027-04-02 16:30:00", 10)
        # 4-minute leading + 10-minute internal + 5-minute trailing OFF;
        # the 8-minute gap from :16 to :24 is still operating time.
        self.assertEqual((result.on_minutes, result.off_minutes), (11, 19))
        self.assertEqual(
            [int((b - a).total_seconds() / 60) for a, b in result.intervals], [4, 10, 5]
        )
        result = off_times(qsos, "2027-04-02 16:00:00", "2027-04-02 16:30:00", 11)
        self.assertEqual((result.on_minutes, result.off_minutes), (21, 9))
        result = off_times([], "2027-04-02 23:59:10", "2027-04-03 00:03:50", 30)
        self.assertEqual((result.on_minutes, result.off_minutes), (0, 3))
        result = off_times(
            [{"TS": "2027-04-02 18:00:00"}],
            "2027-04-02 16:00:00",
            "2027-04-02 18:00:00",
            10,
        )
        self.assertEqual((result.off_minutes, result.outside_qsos), (120, 1))
        with self.assertRaises(UdcError):
            off_times([], "2027-04-02 16:00:00", "2027-04-02 16:00:00")

    def test_snapshot_version_one_remains_unchanged(self):
        # Version one intentionally keeps its original section reader, even if
        # a newer engine understands aliases in the same resource differently.
        old = Bundle(
            self.bundle.filename,
            variant(
                self.bundle,
                StartOfContest="",
                EndOfContest="",
                MinimumOffTime="",
                MultiplierBands="",
            ),
            self.bundle.resources,
            self.bundle.geography_name,
            engine_version=1,
        )
        rows = [self.contacts[2], self.contacts[3]]
        self.assertEqual(
            old.engine(self.station, self.settings).evaluate(rows).score, 0
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = DataBase(root / "versions.db", fsutils.APP_DATA_PATH, 1)
            settings = dict(self.settings, ContestNR=1)
            create_journal(db, settings, old, self.station)
            self.assertEqual(engine_for(db, 1).version, 1)
            self.assertEqual(engine_for(db, 1).evaluate(rows).score, 0)
            catalog = Catalog(root / "catalog")
            identifier = catalog.install(old)
            current = catalog.load(identifier)
            self.assertEqual(current.engine_version, ENGINE_VERSION)
            create_journal(db, dict(settings, ContestNR=2), current, self.station)
            self.assertEqual(engine_for(db, 2).evaluate(rows).score, 2)
            self.assertEqual(Snapshots(db.conn).load(1)[0].engine_version, 1)
            db.conn.close()
