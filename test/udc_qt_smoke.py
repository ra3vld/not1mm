"""Run as a separate process: real Qt widgets, temporary profile, fake CAT only."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
from pathlib import Path
import tempfile
import json
import datetime
from unittest.mock import patch

root = Path(tempfile.mkdtemp(prefix="not1mm-udc-qt-"))
os.environ["XDG_DATA_HOME"] = str(root / "data")
os.environ["XDG_CONFIG_HOME"] = str(root / "config")
from not1mm import fsutils
from not1mm.lib.preferences import Preferences
from not1mm.lib.database import DataBase
from test_udc_engine import fixture, CASES, FIXTURES
from not1mm.udc.storage import Catalog

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
    dict(
        ContestName="general_logging",
        ContestNR=1,
        StartDate="2027-04-02 16:00:00",
        OperatorCategory="SINGLE-OP",
        BandCategory="ALL",
        PowerCategory="LOW",
        ModeCategory="SSB+CW",
        OverlayCategory="N/A",
        Operators="RA3VLD",
        Soapbox="",
        SentExchange="",
        StationCategory="FIXED",
        AssistedCategory="NON-ASSISTED",
        TransmitterCategory="ONE",
    )
)
db.conn.close()
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtTest import QTest
from PyQt6 import QtWidgets

QSettings.setPath(
    QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(root / "config")
)
import not1mm.__main__ as main
import logging

logging.disable(logging.CRITICAL)
from not1mm.lib.new_contest import NewContest
from not1mm.udc.dialog import ImportContestDialog

messages = []
main.MainWindow.show_message_box = lambda self, text, **kwargs: messages.append(text)
w = main.MainWindow(main.splash)
w.show()
main.app.processEvents()
report = []
try:
    for day, (name, case) in enumerate(CASES.items(), 2):
        bundle, own, settings, contacts = fixture(name)
        for q in contacts:
            q["TS"] = q["TS"].replace("2027-04-02", f"2027-04-{day:02}")
        dialog = ImportContestDialog(w)
        dialog.path.setText(str(FIXTURES / case[0]))
        dialog.extra = [str(FIXTURES / "kcj/kcj.sec"), str(FIXTURES / "VLADIMIR/RDACR3V.sec")]
        dialog.geo.setText(str(FIXTURES / (case[3] or "geography/cty.json")))
        dialog.validate()
        assert dialog.bundle is not None, dialog.preview.toPlainText()
        dialog.accept()
        assert dialog.result() == QtWidgets.QDialog.DialogCode.Accepted
        w.station.update(own)
        new = NewContest(fsutils.APP_DATA_PATH)
        index = new.contest.findData(bundle.definition.identifier)
        assert index >= 0
        new.contest.setCurrentIndex(index)
        new.exchange.setText(settings["SentExchange"])
        new.mode.setCurrentText(settings["ModeCategory"])
        new.operator_class.setCurrentText("SINGLE-OP")
        new.band.setCurrentText("ALL")
        new.power.setCurrentText("LOW")
        w.contest_dialog = new
        w.save_contest()
        assert w.contest.d.identifier == bundle.definition.identifier
        w.activateWindow()
        main.app.processEvents()
        for i, q in enumerate(contacts):
            # Follow the actual band-button path, including fake CAT confirmation.
            md = q["Mode"]
            bandname = {1800: "160", 3500: "80", 7000: "40", 14000: "20"}[q["Freq"]]
            button = getattr(
                w, {"CW": "cw", "SSB": "ssb", "RTTY": "rtty"}[md] + "_band_" + bandname
            )
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            QTest.qWait(600)
            if md == "SSB" and bandname == "80":
                assert int(w.radio_state["vfoa"]) == 3650000, w.radio_state
            w.clearinputs()
            w.callsign.setFocus()
            QTest.keyClicks(w.callsign, q["Call"])
            QTest.keyClick(w.callsign, Qt.Key.Key_Tab)
            for col, widget in w.contest.widgets.items():
                widget.setFocus()
                widget.selectAll()
                QTest.keyClicks(widget, str(q.get(col, "")))
            last = list(w.contest.widgets.values())[-1]
            real = datetime.datetime

            class Clock(real):
                @classmethod
                def now(cls, tz=None):
                    return real.strptime(q["TS"], "%Y-%m-%d %H:%M:%S").replace(
                        tzinfo=tz
                    )

            with patch.object(main.datetime, "datetime", Clock):
                QTest.keyClick(last, Qt.Key.Key_Return)
            main.app.processEvents()
            assert len(w.database.fetch_all_contacts_asc()) == i + 1, (
                name,
                i,
                messages,
            )
        if name == "VLADIMIR":
            from not1mm.udc.dialog import OperatingTimeDialog
            from PyQt6.QtCore import QDateTime
            off = OperatingTimeDialog(w.contest, w)
            assert "explicit" in dialog.preview.toPlainText()
            off.start.setDateTime(QDateTime.fromString(f"2027-04-{day:02} 16:00:00", "yyyy-MM-dd HH:mm:ss"))
            off.end.setDateTime(QDateTime.fromString(f"2027-04-{day:02} 18:00:00", "yyyy-MM-dd HH:mm:ss"))
            off.calculate()
            assert "OFF: 118 min" in off.preview.toPlainText(), off.preview.toPlainText()
            assert w.actionUdcOperatingTime.isEnabled()
            off.show()
            main.app.processEvents()
            off.grab().save(str(root / "vladimir-off.png"))
            w.grab().save(str(root / "vladimir-window.png"))
            off.close()
        result = w.contest.result()
        assert result.score == case[6], (name, result, case[6])
        assert result.multipliers == case[7], (name, result)
        assert int(w.score.text()) == case[6], (name, w.score.text())
        w.contest.recalculate_mults(w)
        assert w.contest.calc_score(w) == case[6]
        out = root / (name + ".log")
        with patch.object(
            QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(out), "")
        ):
            w.contest.cabrillo(w, "utf-8")
        assert out.read_text().count("QSO:") == len(contacts)
        adi = root / (name + ".adi")
        with patch.object(
            QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(adi), "")
        ):
            w.contest.adif(w)
        assert adi.read_text().count("<EOR>") == len(contacts)
        original_nr = w.pref["contest"]
        w.save_contest()
        with patch.object(
            QtWidgets.QFileDialog, "getOpenFileName", return_value=(str(adi), "")
        ):
            w.contest.imp_adif(w)
        assert w.contest.show_qso(w) == len(contacts), (name, messages)
        assert w.contest.calc_score(w) == case[6], (name, "ADIF import", messages)
        w.pref["contest"] = original_nr
        w.load_contest()
        w.log_window.get_log()
        w.log_window.generalLog.item(0, w.log_window.get_column("Call")).setText(
            "DL9ZZZ"
        )
        main.app.processEvents()
        edited = w.contest.calc_score(w)
        w.load_contest()
        assert w.contest.calc_score(w) == edited
        # Snapshot remains usable after the original catalog registration disappears.
        for ref in (fsutils.USER_DATA_PATH / "user-contests").glob("udc-*.json"):
            ref.unlink()
        w.load_contest()
        assert w.contest.calc_score(w) == edited
        report.append(
            {
                "definition": name,
                "status": "passed",
                "qso": len(contacts),
                "points": result.points,
                "mults": result.multipliers,
                "score": result.score,
            }
        )
        print(name, "PASS", flush=True)
    # Return to a legacy plugin: no UDC fields or rules must remain active.
    last_udc_nr = w.pref["contest"]
    w.pref["contest"] = 1
    w.load_contest()
    assert not hasattr(w.contest, "engine")
    assert not w.actionUdcOperatingTime.isEnabled()
    w.pref["contest"] = last_udc_nr
    w.load_contest()
    Preferences.save()
    w.grab().save(str(root / "window.png"))
    print(json.dumps(report, indent=2), flush=True)
    (root / "report.json").write_text(json.dumps(report, indent=2))
    print("Artifacts:", root, flush=True)
finally:
    w.close()
    main.app.processEvents()
