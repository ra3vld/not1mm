"""Exercise empty-profile setup through real Qt dialogs in a fresh process.

Run once per case: general_logging, RTC or VLADIMIR. No station/contest rows are seeded.
Only dialog answers and CAT/network preferences are automated.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
import logging
import sys
import tempfile
import traceback
from pathlib import Path
from unittest.mock import patch

root = Path(tempfile.mkdtemp(prefix="not1mm-first-run-"))
os.environ["XDG_DATA_HOME"] = str(root / "data")
os.environ["XDG_CONFIG_HOME"] = str(root / "config")
from not1mm import fsutils
from not1mm.lib.preferences import Preferences

case = sys.argv[1] if len(sys.argv) > 1 else "general_logging"
prefs = dict(Preferences._defaults)
prefs.update(current_database="first-run.db", use_esm=False, logwindow=True)
fsutils.CONFIG_FILE.write_text(json.dumps(prefs))
identifier = "general_logging"
if case in ("RTC", "VLADIMIR"):
    from not1mm.udc.registry import catalog
    from not1mm.udc.storage import read_bundle

    from udc_corpus import require_corpus

    fixtures = require_corpus()
    bundle = read_bundle(
        fixtures / ("RTC/RTC.udc" if case == "RTC" else "VLADIMIR/VLADIMIR.udc"),
        geo=fixtures / "geography/cty.json",
    )
    catalog().install(bundle)
    identifier = bundle.definition.identifier
else:
    assert case == "general_logging", case

from PyQt6.QtCore import QSettings, Qt, QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QDialog, QDialogButtonBox

import not1mm.__main__ as main
from not1mm.lib.edit_station import EditStation
from not1mm.lib.new_contest import NewContest

logging.disable(logging.CRITICAL)
QSettings.setPath(
    QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(root / "config")
)
errors = []
messages = []
dialogs = []
real_exec = QDialog.exec


def exception_hook(kind, value, tb):
    errors.append("".join(traceback.format_exception(kind, value, tb)))
    sys.__excepthook__(kind, value, tb)


def answer_dialog(dialog):
    """Keep the modal event loop and existing accepted/save signal connections."""

    def answer():
        dialogs.append(type(dialog).__name__)
        if isinstance(dialog, EditStation):
            dialog.Call.setText("RA3VLD")
            dialog.Operator.setText("RA3VLD")
            dialog.GridSquare.setText("KO85")
            dialog.CQZone.setText("16")
            dialog.ITUZone.setText("29")
        else:
            index = dialog.contest.findData(identifier)
            assert index >= 0, identifier
            dialog.contest.setCurrentIndex(index)
            dialog.mode.setCurrentText("CW" if case == "RTC" else "SSB+CW")
            dialog.exchange.setText("# KO85" if case in ("RTC", "VLADIMIR") else "")
        QTest.mouseClick(
            dialog.buttonBox.button(QDialogButtonBox.StandardButton.Ok),
            Qt.MouseButton.LeftButton,
        )

    QTimer.singleShot(0, answer)
    return real_exec(dialog)


sys.excepthook = exception_hook
main.MainWindow.show_message_box = lambda self, text, **kwargs: messages.append(text)
w = None
try:
    with (
        patch.object(EditStation, "exec", answer_dialog),
        patch.object(NewContest, "exec", answer_dialog),
        patch.object(
            main.MainWindow,
            "show_message_box",
            lambda self, text, **kwargs: messages.append(text),
        ),
    ):
        w = main.MainWindow(main.splash)
    w.show()
    main.app.processEvents()
    assert not errors, "\n".join(errors)
    assert not messages, messages
    assert dialogs == ["EditStation", "NewContest"], dialogs
    assert w.database.fetch_station()["Call"] == "RA3VLD"
    assert w.contest_settings["ContestName"] == identifier
    assert len(w.database.fetch_all_contests()) == 1
    assert w.check_window.database.current_contest == w.pref["contest"]
    w.callsign.setFocus()
    QTest.keyClicks(w.callsign, "R3AAA")
    QTest.keyClick(w.callsign, Qt.Key.Key_Tab)
    if case in ("RTC", "VLADIMIR"):
        for column, widget in w.contest.widgets.items():
            widget.setText(
                {
                    "NR": "1",
                    "GridSquare": "KO85",
                    "Exchange1": "VL01",
                    "SNT": "599",
                    "RCV": "599",
                }.get(column, widget.text())
            )
        last = list(w.contest.widgets.values())[-1]
    else:
        last = w.other_2
    QTest.keyClick(last, Qt.Key.Key_Return)
    main.app.processEvents()
    assert not errors, "\n".join(errors)
    assert not messages, messages
    assert len(w.database.fetch_all_contacts_asc()) == 1
    # New Contest after startup must still load and notify the initialized docks.
    with patch.object(NewContest, "exec", answer_dialog):
        w.new_contest_dialog()
    assert not errors, "\n".join(errors)
    assert len(w.database.fetch_all_contests()) == 2
    assert (
        w.database.current_contest
        == w.check_window.database.current_contest
        == w.pref["contest"]
    )
    assert w.contest_settings["ContestName"] == identifier
    print(
        json.dumps(
            {
                "case": case,
                "status": "passed",
                "dialogs": dialogs,
                "profile": str(root),
                "source": main.__file__,
            }
        ),
        flush=True,
    )
finally:
    if w is not None:
        w.close()
        main.app.processEvents()
