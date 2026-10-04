"""Open a saved temporary UDC profile in a fresh interpreter; no launcher injection."""

import os
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
os.environ["XDG_DATA_HOME"] = str(root / "data")
os.environ["XDG_CONFIG_HOME"] = str(root / "config")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QSettings

QSettings.setPath(
    QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(root / "config")
)
import not1mm.__main__ as main
import logging

logging.disable(logging.CRITICAL)
messages = []
main.MainWindow.show_message_box = lambda self, text, **kwargs: messages.append(text)
w = main.MainWindow(main.splash)
try:
    assert hasattr(w.contest, "engine"), messages
    assert w.contest.show_qso(w) > 0
    expected = w.contest.calc_score(w)
    assert int(w.score.text()) == expected, (w.score.text(), expected)
    assert not list((root / "data/not1mm/user-contests").glob("udc-*.json"))
    print("RESTART PASS", w.contest.name, expected, main.__file__)
    w.grab().save(str(root / "reopened.png"))
finally:
    w.close()
    main.app.processEvents()
