"""Run as a separate process: real Qt widgets, temporary profile, fake CAT only."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import datetime
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

root = Path(tempfile.mkdtemp(prefix="not1mm-runtime-qt-"))
os.environ["XDG_DATA_HOME"] = str(root / "data")
os.environ["XDG_CONFIG_HOME"] = str(root / "config")

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
from PyQt6 import QtWidgets
from PyQt6.QtCore import QSettings, Qt, QTimer
from PyQt6.QtTest import QTest

QSettings.setPath(
    QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(root / "config")
)
import logging

import not1mm.__main__ as main

logging.disable(logging.CRITICAL)
from not1mm.lib.new_contest import NewContest
from not1mm.lib.settings import Settings
from not1mm.udc.dialog import ImportContestDialog

messages = []
main.MainWindow.show_message_box = lambda self, text, **kwargs: messages.append(text)
w = main.MainWindow(main.splash)
w.show()
main.app.processEvents()

from PyQt6 import QtNetwork
from udc_runtime_fixture import GEO, definition, udp_packet

import not1mm.udc.plugin as adapter
from not1mm.udc.export import adif, cabrillo
from not1mm.udc.plugin import UdcContest

# Use a private ephemeral UDP port; never deliver test QSOs to a user's logger.
w.ft8.udp_socket.close()
assert w.ft8.udp_socket.bind(QtNetwork.QHostAddress.SpecialAddress.LocalHost, 0)
port = w.ft8.udp_socket.localPort()
sender = QtNetwork.QUdpSocket()


def new_journal(d):
    source = root / "runtime.udc"
    source.write_bytes(d.original)
    geo = root / "cty.json"
    geo.write_text(json.dumps(GEO))
    dialog = ImportContestDialog(w)
    dialog.path.setText(str(source))
    dialog.geo.setText(str(geo))
    dialog.validate()
    assert dialog.bundle is not None, dialog.preview.toPlainText()
    dialog.accept()
    assert dialog.result() == QtWidgets.QDialog.DialogCode.Accepted
    new = NewContest(fsutils.APP_DATA_PATH)
    index = new.contest.findData(d.identifier)
    assert index >= 0
    new.contest.setCurrentIndex(index)
    new.operator_class.setCurrentText("SINGLE-OP")
    new.exchange.setText("# KO85")
    new.mode.setCurrentText("SSB+CW+DIGITAL")
    w.contest_dialog = new
    w.save_contest()
    assert isinstance(w.contest, UdcContest)
    assert w.ft8.callback == w.contest.ft8_handler
    assert w.contest.engine.version == 3
    return w.pref["contest"]


external_sequence = 0


def deliver(record):
    global external_sequence
    ready = os.environ.get("UDC_UDP_READY")
    if ready:
        external_sequence += 1
        path = Path(ready)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"sequence": external_sequence, "port": port, "record": record})
        )
        temporary.replace(path)
        acknowledgement = path.with_suffix(".sent")
        for _ in range(500):
            QTest.qWait(20)
            if acknowledgement.exists() and acknowledgement.read_text() == str(
                external_sequence
            ):
                break
        else:
            raise AssertionError("External UDP sender did not acknowledge the packet")
        QTest.qWait(100)
        main.app.processEvents()
        return
    sender.writeDatagram(
        udp_packet(record), QtNetwork.QHostAddress.SpecialAddress.LocalHost, port
    )
    QTest.qWait(100)
    main.app.processEvents()


try:
    d = definition(
        PointsPerContact="FT8,2,FT4,3,DIGI,4,CW,1",
        SingleOpCountableBandChange=True,
        SOBandChangeCountMax=2,
        CountBandOrModeChange=True,
        SOBandChangeTimerDuration=10,
    )
    ft_nr = new_journal(d)
    w.callsign.setText("K1ZZZ")
    w.contest.widgets["GridSquare"].setText("FN31")

    # Saving options and changing language must preserve UDC labels and an entry.
    def settings_exec(dialog):
        def answer():
            index = dialog.language.findData(requested_language)
            assert index >= 0
            dialog.language.setCurrentIndex(index)
            QtWidgets.QApplication.processEvents()
            QTest.mouseClick(
                dialog.buttonBox.button(QtWidgets.QDialogButtonBox.StandardButton.Save),
                Qt.MouseButton.LeftButton,
            )

        QTimer.singleShot(0, answer)
        return QtWidgets.QDialog.exec(dialog)

    for requested_language in ("ru", "ru", "en_US"):
        with patch.object(Settings, "exec", settings_exec):
            w.edit_configuration_settings()
        assert w.pref["language"] == requested_language
        assert w.contest.labels["GridSquare"].text() == "Grid"
        assert w.contest.widgets["GridSquare"].text() == "FN31"
        assert w.callsign.text() == "K1ZZZ"

    packets = []
    for time, md, frequency in [
        ("160000", "FT8", "3.573"),
        ("160030", "FT4", "3.573"),
        ("160100", "FT8", "3.573"),
        ("160200", "FT8", "7.074"),
    ]:
        record = {
            "QSO_DATE": "20270402",
            "TIME_ON": time,
            "MODE": md if md == "FT8" else "MFSK",
            "CALL": "DL1AAA",
            "FREQ": frequency,
            "GRIDSQUARE": "JO62",
            "RST_SENT": "-10",
            "RST_RCVD": "+03",
            "STATION_CALLSIGN": "RA3VLD",
        }
        if md == "FT4":
            record["SUBMODE"] = "FT4"
        packets.append(record)
        deliver(record)
    rows = w.contest.rows()
    assert len(rows) == 4, (rows, messages)
    assert [q["Points"] for q in rows] == [2, 3, 0, 2]
    assert [q["TS"][-8:] for q in rows] == [
        "16:00:00",
        "16:00:30",
        "16:01:00",
        "16:02:00",
    ]
    assert [q["Freq"] for q in rows] == [3573, 3573, 3573, 7074]
    assert all(q["SNT"] == "-10" and q["RCV"] == "+03" for q in rows)
    assert w.score.text() == "21"
    assert (
        w.callsign.text() == "K1ZZZ"
        and w.contest.widgets["GridSquare"].text() == "FN31"
    )
    deliver(packets[0])
    assert len(w.contest.rows()) == 4
    w.contest.refresh_status("2027-04-02 16:02:00")
    assert "3/2" in w.contest.status_label.text()
    assert "10:00" in w.contest.status_label.text()
    assert "#b3261e" in w.contest.status_label.styleSheet()
    assert "hold timer" in w.contest.status_label.toolTip()
    w.grab().save(str(root / "band-status.png"))
    assert "CLAIMED-SCORE: 21" in cabrillo(w.contest.engine, rows)
    assert cabrillo(w.contest.engine, rows).count(" DG ") == 4
    text = adif(w.contest.engine, rows)
    assert "<SUBMODE:3>FT4" in text
    old_timer = w.contest.status_timer
    w.load_contest()
    assert not old_timer.isActive()
    deliver(packets[0])
    assert len(w.contest.rows()) == 4  # delivery identity survives reload

    interval_nr = new_journal(
        definition(
            Name="INTERVAL", DupeType=4, DupeQSOMinutesAgo="10,True,False,True,False"
        )
    )
    real = datetime.datetime

    class Clock(real):
        @classmethod
        def now(cls, tz=None):
            return cls(2027, 4, 2, 16, 0, 0, tzinfo=tz)

    # Real 80 m SSB button and Tab/Enter entry, optional report inputs preserved.
    QTest.mouseClick(w.ssb_band_80, Qt.MouseButton.LeftButton)
    QTest.qWait(600)
    assert int(w.radio_state["vfoa"]) == 3650000, w.radio_state
    with (
        patch.object(adapter, "datetime", Clock),
        patch.object(main.datetime, "datetime", Clock),
    ):
        w.clearinputs()
        QTest.keyClicks(w.callsign, "DL1AAA")
        QTest.keyClick(w.callsign, Qt.Key.Key_Tab)
        widget = w.contest.widgets["GridSquare"]
        QTest.keyClicks(widget, "JO62")
        QTest.keyClick(widget, Qt.Key.Key_Return)
    assert len(w.contest.rows()) == 1, messages
    w.callsign.setText("DL1AAA")
    w.contest.widgets["GridSquare"].setText("JO62")
    with patch.object(adapter, "datetime", Clock):
        w.contest.refresh_status()
        assert w.contact_is_dupe
        assert w.bandmap_window.spot_is_worked(
            {"callsign": "DL1AAA", "freq": 3.65, "comment": "SSB"}
        )
        assert "worked 0.0 minutes ago" in w.contest.status_label.text()

    class Later(Clock):
        @classmethod
        def now(cls, tz=None):
            return cls(2027, 4, 2, 16, 10, 0, tzinfo=tz)

    with patch.object(adapter, "datetime", Later):
        w.contest.refresh_status()
        assert not w.contact_is_dupe
        assert not w.bandmap_window.spot_is_worked(
            {"callsign": "DL1AAA", "freq": 3.65, "comment": "SSB"}
        )
        assert "worked" not in w.contest.status_label.text()
    retired = w.contest.status_timer
    retired_callback = w.ft8.callback
    w.pref["contest"] = 1
    w.load_contest()
    assert w.ft8.callback != retired_callback
    assert not hasattr(w.contest, "engine")
    assert w.bandmap_window.udc_dupe_checker is None
    assert not retired.isActive()
    w.pref["contest"] = ft_nr
    w.load_contest()
    assert w.contest.show_qso(w) == 4 and w.score.text() == "21"
    for ref in (fsutils.USER_DATA_PATH / "user-contests").glob("udc-*.json"):
        ref.unlink()
    report = {
        "status": "passed",
        "source": main.__file__,
        "profile": str(root),
        "ft_journal": ft_nr,
        "interval_journal": interval_nr,
        "points": 7,
        "multipliers": 3,
        "score": 21,
        "qso": 4,
        "messages": messages,
    }
    assert not messages, messages
    (root / "runtime-report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)
finally:
    sender.close()
    w.close()
    main.app.processEvents()
