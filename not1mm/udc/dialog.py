"""Review an original UDC and its dependencies before atomic catalog installation."""

from pathlib import Path

from PyQt6 import QtWidgets

from .model import UdcError
from .registry import catalog
from .storage import read_bundle


class ImportContestDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import User Contest")
        self.resize(700, 500)
        layout = QtWidgets.QVBoxLayout(self)
        self.path = QtWidgets.QLineEdit(self)
        browse = QtWidgets.QPushButton("Choose UDC…", self)
        browse.clicked.connect(self.choose_udc)
        layout.addWidget(self.path)
        layout.addWidget(browse)
        self.encoding = QtWidgets.QComboBox(self)
        self.encoding.addItems(["UTF-8 / Unicode BOM", "cp1251", "cp1252", "latin-1"])
        layout.addWidget(self.encoding)
        self.extra = []
        deps = QtWidgets.QPushButton("Add dependency files (.sec / .txt)…", self)
        deps.clicked.connect(self.choose_dependencies)
        layout.addWidget(deps)
        self.geo = QtWidgets.QLineEdit(self)
        self.geo.setPlaceholderText(
            "Geography: bundled cty.json (or select contest CTY.DAT)"
        )
        layout.addWidget(self.geo)
        geo = QtWidgets.QPushButton("Choose contest geography…", self)
        geo.clicked.connect(self.choose_geography)
        layout.addWidget(geo)
        self.preview = QtWidgets.QPlainTextEdit(self)
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview)
        check = QtWidgets.QPushButton("Validate and preview", self)
        check.clicked.connect(self.validate)
        layout.addWidget(check)
        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText(
            "Import"
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        for edit in (self.path, self.geo):
            edit.textChanged.connect(self.invalidate)
        self.encoding.currentIndexChanged.connect(self.invalidate)
        self.bundle = None
        self.invalidate()

    def invalidate(self, *args):
        self.bundle = None
        self.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setEnabled(
            False
        )

    def choose_udc(self):
        name, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose original UDC", "", "UDC (*.udc *.UDC)"
        )
        if name:
            self.path.setText(name)
            candidates = list(Path(name).parent.glob("*cty.dat"))
            if len(candidates) == 1:
                self.geo.setText(str(candidates[0]))
            self.validate()

    def choose_dependencies(self):
        names, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "Choose original dependencies",
            "",
            "Support files (*.sec *.txt *.SEC *.TXT)",
        )
        self.extra = names
        self.invalidate()
        self.validate()

    def choose_geography(self):
        name, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose geography", "", "Geography (*.dat *.json)"
        )
        if name:
            self.geo.setText(name)
            self.validate()

    def validate(self):
        self.invalidate()
        try:
            bundle = read_bundle(
                self.path.text(),
                None
                if self.encoding.currentIndex() == 0
                else self.encoding.currentText(),
                self.extra,
                self.geo.text() or None,
            )
            d = bundle.definition
            lines = [
                d.label,
                f"ID: {d.identifier}",
                f"Revision: {d.revision}",
                f"Author: {d.author.get('authorname', '')} ({d.author.get('callsign', '')})",
                f"Mode: {d.get('mode', 'CW')}",
                f"Cabrillo CONTEST: {d.get('cabrilloname', d.get('name'))}",
                f"Exchange: {d.get('frametext')}",
                f"Points: {d.get('pointspercontact', '1')}",
                f"Multipliers: {d.get('nummults', '1')}",
                f"Sessions: {d.get('multiplesessions', 'none')}",
                f"Repeat interval: {d.get('dupeqsominutesago', 'disabled')}",
                f"SO band changes: enabled={d.flag('singleopcountablebandchange')}, limit={d.integer('sobandchangecountmax')}, timer={d.integer('sobandchangetimerduration')} min",
                f"MO band changes: enabled={d.flag('multiopcountablebandchange')}, limit={d.integer('mobandchangecountmax')}, timer={d.integer('mobandchangetimerduration')} min",
                f"Multiplier bands: {d.get('multiplierbands', '1')} (HF contest / all HF / HF + 6m, 2m / VHF)",
                f"OFF calendar: {d.start.describe() if d.start else 'not specified'} → {d.end.describe() if d.end else 'not specified'}",
                f"Minimum OFF interval: {d.integer('minimumofftime', 30)} min; calendar does not restrict QSO scoring",
                "OFF times require an explicit report end for identical calendar endpoints."
                if d.start is not None and d.start == d.end
                else "",
                "Files: " + ", ".join(bundle.files()),
                "Geography: " + bundle.geography_name,
                d.get("specialinstructions"),
                "New journals use this revision. Existing journals retain their saved rules.",
            ]
            self.preview.setPlainText("\n".join(lines))
            self.bundle = bundle
            self.buttons.button(
                QtWidgets.QDialogButtonBox.StandardButton.Ok
            ).setEnabled(True)
        except (UdcError, OSError, ValueError) as exc:
            self.preview.setPlainText(str(exc))

    def accept(self):
        # Re-read to prevent importing a file changed after preview without review.
        previous = self.bundle.payload() if self.bundle else None
        self.validate()
        if self.bundle is None:
            return
        if self.bundle.payload() != previous:
            self.preview.appendPlainText(
                "Files changed. Review the new preview and press Import again."
            )
            return
        try:
            catalog().install(self.bundle)
        except OSError as exc:
            self.preview.appendPlainText(str(exc))
            return
        super().accept()


class OperatingTimeDialog(QtWidgets.QDialog):
    """Review actual UTC dates when a recurring calendar hint is ambiguous."""

    def __init__(self, contest, parent=None):
        from PyQt6.QtCore import QDateTime

        from .operating import schedule_window

        super().__init__(parent)
        self.contest = contest
        self.setWindowTitle("UDC operating / OFF times")
        self.resize(700, 450)
        layout = QtWidgets.QVBoxLayout(self)
        d = contest.d
        hints = [x.describe() if x else "not specified" for x in (d.start, d.end)]
        label = QtWidgets.QLabel(
            f"UDC calendar: {hints[0]} → {hints[1]}\nChoose the actual UTC interval for this report. Minimum internal break: {d.integer('minimumofftime', 30)} min.",
            self,
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        form = QtWidgets.QFormLayout()
        self.start = QtWidgets.QDateTimeEdit(self)
        self.end = QtWidgets.QDateTimeEdit(self)
        for widget in (self.start, self.end):
            widget.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
            widget.setCalendarPopup(True)
        anchor = contest.engine.settings.get("StartDate", "")
        _, end = schedule_window(d, anchor)
        self.start.setDateTime(QDateTime.fromString(anchor, "yyyy-MM-dd HH:mm:ss"))
        self.end.setDateTime(
            QDateTime.fromString(
                end.strftime("%Y-%m-%d %H:%M:%S") if end else anchor,
                "yyyy-MM-dd HH:mm:ss",
            )
        )
        form.addRow("Start (UTC)", self.start)
        form.addRow("End (UTC)", self.end)
        layout.addLayout(form)
        self.preview = QtWidgets.QPlainTextEdit(self)
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview)
        calculate = QtWidgets.QPushButton("Calculate", self)
        calculate.clicked.connect(self.calculate)
        layout.addWidget(calculate)
        close = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Close, self
        )
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        if end is None:
            self.preview.setPlainText(
                "This UDC has no distinct end time. Set the actual end before calculating OFF times."
            )
        else:
            self.calculate()

    def calculate(self):
        try:
            result = self.contest.engine.off_times(
                self.contest.rows(),
                self.start.dateTime().toString("yyyy-MM-dd HH:mm:ss"),
                self.end.dateTime().toString("yyyy-MM-dd HH:mm:ss"),
            )
            self.preview.setPlainText(result.text())
        except UdcError as exc:
            self.preview.setPlainText(str(exc))
