"""Real Call History import, Tab/Space/mouse transitions and retained UDC journals."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import datetime
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

root = Path(tempfile.mkdtemp(prefix="not1mm-callhistory-qt-"))
os.environ["XDG_DATA_HOME"] = str(root / "data")
os.environ["XDG_CONFIG_HOME"] = str(root / "config")
from test_udc_engine import fixture

from not1mm import fsutils
from not1mm.lib.database import DataBase
from not1mm.lib.preferences import Preferences

prefs = dict(Preferences._defaults)
prefs.update(
    current_database="qa.db",
    contest=1,
    current_op="RA3VLD",
    use_esm=False,
    useserver=False,
    im_the_master=False,
    send_rtc_scores=False,
    send_n1mm_packets=False,
    useqrz=False,
    usehamqth=False,
    usehamdb=False,
    userigctld=False,
    useflrig=False,
    usetci=False,
    cwtype=0,
    logwindow=True,
    bandmapwindow=False,
    clusterwindow=False,
    cloudlog=False,
    bands=["160m", "80m", "40m", "20m"],
    run_state=True,
)
fsutils.CONFIG_FILE.write_text(json.dumps(prefs))
db = DataBase(fsutils.USER_DATA_PATH / "qa.db", fsutils.APP_DATA_PATH, 1)
station = {
    "Call": "RA3VLD",
    "Name": "",
    "Email": "",
    "Street1": "",
    "Street2": "",
    "City": "",
    "State": "",
    "Zip": "",
    "Country": "",
    "GridSquare": "KO85",
    "CQZone": 16,
    "IARUZone": 29,
    "Club": "",
    "ARRLSection": "",
    "RoverQTH": "",
}
db.add_station(station)
db.add_contest(
    {
        "ContestName": "general_logging",
        "ContestNR": 1,
        "StartDate": "2027-04-02 16:00:00",
        "OperatorCategory": "SINGLE-OP",
        "BandCategory": "ALL",
        "PowerCategory": "LOW",
        "ModeCategory": "SSB+CW",
        "OverlayCategory": "N/A",
        "Operators": "RA3VLD",
        "Soapbox": "",
        "SentExchange": "",
        "StationCategory": "FIXED",
        "AssistedCategory": "NON-ASSISTED",
        "TransmitterCategory": "ONE",
    }
)
db.conn.close()
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtTest import QTest

QSettings.setPath(
    QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(root / "config")
)
import logging

import not1mm.__main__ as main

logging.disable(logging.CRITICAL)

messages = []
main.MainWindow.show_message_box = lambda self, text, **kwargs: messages.append(text)
w = main.MainWindow(main.splash)
w.show()
main.app.processEvents()

import csv

from not1mm.udc.storage import Bundle, Snapshots

w.ft8.udp_socket.close()
sample = root / "history.txt"
with sample.open("w", newline="", encoding="utf-8") as stream:
    writer = csv.writer(stream)
    writer.writerow(
        ["!!Order!!", "Call", "Name", "Exch1", "Loc1", "Sect", "State", "UserText", ""]
    )
    writer.writerows(
        [
            ["R3VL", "", "VL13", "KO96", "VL13", "VL", "VL13 (KO96)", ""],
            ["RA3VLD", "", "VL02", "", "VL02", "VL", "VL02", ""],
            ["UA3PP", "", "KO84", "KO84", "", "TL", "KO84", ""],
            ["RU3TC", "", "NN", "", "", "NN", "NN (область; локатор неизвестен)", ""],
            ["DL1AAA", "", "JO62", "JO62", "", "", "Grid JO62, quoted CSV comment", ""],
        ]
    )
history = Path(os.environ.get("UDC_CALLHISTORY_FILE", str(sample)))
expected = sum(
    1
    for row in csv.reader(history.read_text().splitlines())
    if row and not row[0].startswith(("#", "!!"))
)


def type_call(call, leave=None):
    w.clearinputs()
    w.callsign.setFocus()
    QTest.keyClicks(w.callsign, call)
    main.app.processEvents()
    if leave is not None:
        QTest.keyClick(w.callsign, leave)
        main.app.processEvents()


report = []
try:
    with patch.object(w, "filepicker", return_value=str(history)):
        w.load_call_history()
    assert not messages, messages
    assert w.database.exec_sql("SELECT COUNT(*) AS n FROM CALLHISTORY")["n"] == expected
    assert str(expected) in w.statusBar().currentMessage()
    assert "enable Use Call History" in w.statusBar().currentMessage()
    if history == sample:
        assert (
            w.database.fetch_call_history("DL1AAA")["UserText"]
            == "Grid JO62, quoted CSV comment"
        )
    w.use_call_history = True
    w.pref["use_call_history"] = True
    w.history_info.show()

    # Exercise already-saved engine 2 journals as well as new engine 3 journals.
    for version in (2, 3):
        original, own, settings, _ = fixture("VLADIMIR")
        bundle = Bundle(
            original.filename,
            original.definition,
            original.resources,
            original.geography_name,
            engine_version=version,
        )
        nr = w.database.get_next_contest_nr()["nr"]
        w.database.add_contest(dict(settings, ContestNR=nr))
        Snapshots(w.database.conn).create(nr, bundle, own)
        w.pref["contest"] = nr
        w.load_contest()
        w.activateWindow()
        main.app.processEvents()
        QTest.mouseClick(w.cw_band_80, Qt.MouseButton.LeftButton)
        QTest.qWait(600)
        assert 3500000 <= int(w.radio_state["vfoa"]) <= 3800000, w.radio_state
        assert w.contest.engine.version == version
        p = w.contest

        type_call("R3VL")
        assert "VL13" in w.history_info.text(), w.history_info.text()
        assert p.widgets["Exchange1"].text() == "", (
            p.widgets["Exchange1"].text(),
            p._history_prefilled,
            p._history_call,
        )
        QTest.keyClick(w.callsign, Qt.Key.Key_Tab)
        main.app.processEvents()
        assert p.widgets["Exchange1"].text() == "VL13"
        assert p.widgets["NR"].text() == ""
        assert p.widgets["NR"].hasFocus()

        type_call("UA3PP", Qt.Key.Key_Space)
        assert p.widgets["Exchange1"].text() == "KO84"
        assert p.widgets["NR"].text() == ""

        type_call("RA3VLD")
        QTest.mouseClick(p.widgets["NR"], Qt.MouseButton.LeftButton)
        main.app.processEvents()
        assert p.widgets["Exchange1"].text() == "VL02"

        type_call("RU3TC", Qt.Key.Key_Tab)
        assert "NN" in w.history_info.text()
        assert p.widgets["Exchange1"].text() == ""

        # An operator edit, even back to the original suggested value, owns it.
        type_call("R3VL", Qt.Key.Key_Tab)
        p.widgets["Exchange1"].setFocus()
        p.widgets["Exchange1"].selectAll()
        QTest.keyClicks(p.widgets["Exchange1"], "VL13")
        w.callsign.setText("UA3PP")
        QTest.keyClick(w.callsign, Qt.Key.Key_Tab)
        assert p.widgets["Exchange1"].text() == "VL13"

        # Changing a call discards the old automatic value, not the received NR.
        type_call("R3VL", Qt.Key.Key_Tab)
        p.widgets["NR"].setText("023")
        QTest.mouseClick(w.callsign, Qt.MouseButton.LeftButton)
        w.callsign.selectAll()
        QTest.keyClicks(w.callsign, "UA3PP")
        main.app.processEvents()
        assert p.widgets["Exchange1"].text() == "", (
            p.widgets["Exchange1"].text(),
            p._history_prefilled,
            p._history_call,
        )
        assert p.widgets["NR"].text() == "023"
        QTest.keyClick(w.callsign, Qt.Key.Key_Tab)
        assert p.widgets["Exchange1"].text() == "KO84"

        type_call("R3VL/P", Qt.Key.Key_Tab)
        assert p.widgets["Exchange1"].text() == ""
        assert w.history_info.text() == ""

        w.use_call_history = False
        type_call("R3VL", Qt.Key.Key_Tab)
        assert p.widgets["Exchange1"].text() == ""
        w.use_call_history = True

        type_call("R3VL", Qt.Key.Key_Tab)
        p.widgets["NR"].setText("023")
        before = {key: widget.text() for key, widget in p.widgets.items()}
        w.retranslate_contest_labels()
        assert {key: widget.text() for key, widget in p.widgets.items()} == before
        for field in p.d.fields:
            assert p.labels[field.column].text() == field.label
        if p.status_timer is not None:
            QTest.qWait(1100)
            assert "VL13" in w.history_info.text()

        real = datetime.datetime

        class Clock(real):
            @classmethod
            def now(cls, tz=None, real=real):
                return real(2027, 4, 2, 16, 1, tzinfo=tz)

        with patch.object(main.datetime, "datetime", Clock):
            QTest.keyClick(p.widgets["NR"], Qt.Key.Key_Return)
        rows = p.rows()
        assert len(rows) == 1, messages
        assert rows[0]["Exchange1"] == rows[0]["Sect"] == "VL13"
        assert int(rows[0]["NR"]) == 23
        assert rows[0]["Points"] == 1
        assert p.calc_score(w) == 1
        assert not messages, messages
        w.pref["contest"] = 1
        w.load_contest()
        w.pref["contest"] = nr
        w.load_contest()
        assert w.contest.engine.version == version
        type_call("UA3PP", Qt.Key.Key_Tab)
        assert w.contest.widgets["Exchange1"].text() == "KO84"
        w.grab().save(str(root / f"history-engine-{version}.png"))
        report.append(
            {
                "engine": version,
                "entries": expected,
                "qso": 1,
                "score": 1,
                "status": "passed",
            }
        )

    # Original module plugins and a retained engine 1 grid journal still work.
    original, own, settings, _ = fixture("RTC")
    bundle = Bundle(
        original.filename,
        original.definition,
        original.resources,
        original.geography_name,
        engine_version=1,
    )
    nr = w.database.get_next_contest_nr()["nr"]
    w.database.add_contest(dict(settings, ContestNR=nr))
    Snapshots(w.database.conn).create(nr, bundle, own)
    w.pref["contest"] = nr
    w.load_contest()
    type_call("R3VL", Qt.Key.Key_Tab)
    assert w.contest.widgets["GridSquare"].text() == "KO96"
    assert w.contest.engine.version == 1
    assert w.history_info.text()

    invalid = root / "invalid.hlp"
    for content in (
        "R3VL VL13\n",
        "!!Order!!,Call,Loc1,Loc1\nR3VL,KO96,KO96\n",
        "!!Order!!,Call,NotAColumn\nR3VL,value\n",
        "!!Order!!,Call,Loc1\n",
        '!!Order!!,Call,UserText\nR3VL,"unterminated quote\n',
    ):
        invalid.write_text(content)
        with patch.object(w, "filepicker", return_value=str(invalid)):
            w.load_call_history()
        assert messages, content
        messages.clear()
        assert (
            w.database.exec_sql("SELECT COUNT(*) AS n FROM CALLHISTORY")["n"]
            == expected
        )
        assert w.database.fetch_call_history("R3VL")["Exch1"] == "VL13"
    Preferences.save()
    (root / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)
    print("Artifacts:", root, flush=True)
finally:
    w.close()
    main.app.processEvents()
