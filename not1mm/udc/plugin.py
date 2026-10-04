"""One per-journal UDC adapter for not1mm's plugin API."""

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from PyQt6 import QtCore, QtWidgets

from . import export
from .engine import band, grid_position, mode
from .model import UdcError, pairs

COLUMNS = {
    "SNT": "Snt",
    "RCV": "Rcv",
    "NR": "RcvNr",
    "Points": "PTS",
    "SentReport": "Snt",
    "ReceiveReport": "Rcv",
    "SentNR": "SentNr",
    "IsMultiplier1": "M1",
    "IsMultiplier2": "M2",
    "IsMultiplier3": "M3",
}


class UdcContest:
    dupe_type = 5
    advance_on_space = [True] * 5

    def __init__(self, bundle, database, station, settings):
        self.bundle = bundle
        self.d = bundle.definition
        self.database = database
        self.engine = bundle.engine(station, settings) if database else None
        self.name = self.d.label
        self.cabrillo_name = self.d.get("cabrilloname", self.d.get("name"))
        self.mode = self.d.get("mode", "CW")
        self.EXCHANGE_HINT = self.d.get("defaultcontestexchange")
        self.SOAPBOX_HINT = self.d.get("specialinstructions")
        self.columns = ["YYYY-MM-DD HH:MM:SS", "Call", "Freq (KHz)", "Mode"]
        self.columns += [
            COLUMNS.get(k, k) for k, _ in pairs(self.d.get("loginfo"), "LogInfo")
        ]
        self.columns += ["Operator"]
        self.widgets = {}
        self.frames = {}
        self.labels = {}
        self.extra = []
        self._history_call = ""
        self._history_prefilled = {}
        self._history_edit_handlers = []
        self._callsign_had_focus = False
        self.window = None
        self.status_label = None
        self.status_timer = None
        self._repeat_index = {}
        self._repeat_time = ""

    def set_self(self, w):
        self.window = w

    def init_contest(self, w):
        self.previous_station = dict(w.station)
        w.station = dict(self.engine.station)
        self.prefilled_serial = ""
        base = {
            "SNT": (w.field1, w.snt_label, w.sent),
            "RCV": (w.field2, w.rcv_label, w.receive),
        }
        spare = iter(
            [(w.field3, w.other_label, w.other_1), (w.field4, w.exch_label, w.other_2)]
        )
        for frame in (w.field1, w.field2, w.field3, w.field4):
            frame.hide()
        for field in self.d.fields:
            if field.column in base:
                frame, label, widget = base[field.column]
            else:
                candidate = next(spare, None)
                if candidate is not None:
                    frame, label, widget = candidate
                else:
                    frame = QtWidgets.QFrame(w)
                    layout = QtWidgets.QVBoxLayout(frame)
                    label = QtWidgets.QLabel(frame)
                    widget = QtWidgets.QLineEdit(frame)
                    widget.setFont(w.other_1.font())
                    layout.addWidget(label)
                    layout.addWidget(widget)
                    w.horizontalLayout.addWidget(frame)
                    widget.installEventFilter(w)
                    self.extra.append(frame)
            label.setText(field.label)
            widget.setAccessibleName(field.label)
            widget.setMinimumWidth(max(60, min(220, field.width // 7)))
            widget.setMaxLength(60 if field.column == "Comment" else 20)
            frame.show()
            self.widgets[field.column] = widget
            self.frames[field.column] = frame
            self.labels[field.column] = label
            edited = lambda _text, col=field.column: self._history_prefilled.pop(
                col, None
            )
            widget.textEdited.connect(edited)
            self._history_edit_handlers.append((widget, edited))
        self.interface(w)
        self.set_tab_next(w)
        self.set_tab_prev(w)
        self.set_self(w)
        self.reset_inputs(w)
        self._callsign_had_focus = w.callsign.hasFocus()
        if self.engine.version >= 3:
            self.status_label = QtWidgets.QLabel(w)
            self.status_label.setAccessibleName("UDC operating status")
            w.statusBar().addPermanentWidget(self.status_label, 1)
            self.status_timer = QtCore.QTimer(w)
            self.status_timer.setInterval(1000)
            self.status_timer.timeout.connect(self.refresh_status)
            self.status_timer.start()
            self.refresh_status()
            if w.bandmap_window and self.d.repeat.minutes:
                w.bandmap_window.udc_dupe_checker = self.bandmap_repeat

    def interface(self, w):
        """Reapply UDC labels after UI translation without resetting an entry."""
        active = set(self.frames.values())
        for frame in (w.field1, w.field2, w.field3, w.field4, *self.extra):
            frame.setVisible(frame in active)
        for field in self.d.fields:
            self.labels[field.column].setText(field.label)
            self.widgets[field.column].setAccessibleName(field.label)

    def set_tab_next(self, w):
        widgets = [w.callsign] + list(self.widgets.values())
        w.tab_next = {
            item: widgets[(i + 1) % len(widgets)] for i, item in enumerate(widgets)
        }
        received = [
            self.widgets[f.column]
            for f in self.d.fields
            if f.column not in ("SNT", "SentNr", "RCV")
        ]
        w.next_field = received[0] if received else w.callsign
        # Default callsign Tab goes straight to the received exchange; reverse Tab
        # and normal field order still make reports / transmitted serial editable.
        w.tab_next[w.callsign] = w.next_field

    def set_tab_prev(self, w):
        widgets = [w.callsign] + list(self.widgets.values())
        w.tab_prev = {
            item: widgets[(i - 1) % len(widgets)] for i, item in enumerate(widgets)
        }

    def teardown(self, w):
        if w.bandmap_window:
            w.bandmap_window.udc_dupe_checker = None
        self._repeat_index = {}
        self._repeat_time = ""
        if self.status_timer is not None:
            self.status_timer.stop()
            self.status_timer.deleteLater()
            self.status_timer = None
        if self.status_label is not None:
            w.statusBar().removeWidget(self.status_label)
            self.status_label.deleteLater()
            self.status_label = None
        self.window = None
        w.station = self.previous_station
        for widget, edited in self._history_edit_handlers:
            widget.textEdited.disconnect(edited)
        self._history_edit_handlers = []
        self._history_prefilled = {}
        self._history_call = ""
        self._callsign_had_focus = False
        for frame in self.extra:
            w.horizontalLayout.removeWidget(frame)
            frame.deleteLater()
        self.extra = []
        self.widgets = {}
        self.frames = {}
        self.labels = {}

    def reset_inputs(self, w):
        self._history_call = ""
        self._history_prefilled = {}
        for widget in self.widgets.values():
            widget.clear()
        md = mode(w.radio_state.get("mode", w.current_mode))
        rst = "" if md in ("FT8", "FT4") else "59" if md == "SSB" else "599"
        for col in ("SNT", "RCV"):
            if col in self.widgets:
                self.widgets[col].setText(rst)
        self.prefill(w)

    def key_event(self, w, obj, event):
        if obj not in [w.callsign, *self.widgets.values()]:
            return False
        key = event.key()
        if key in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            w.save_contact()
            return True
        if key in (QtCore.Qt.Key.Key_Tab, QtCore.Qt.Key.Key_Backtab):
            if obj == w.callsign:
                w.check_callsign(w.callsign.text())
                self.prefill(w)
                self.check_call_history(w)
            previous = key == QtCore.Qt.Key.Key_Backtab or bool(
                event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier
            )
            (w.tab_prev if previous else w.tab_next)[obj].setFocus()
            return True
        return False

    def rows(self):
        return self.database.fetch_all_contacts_asc()

    def result(self):
        return self.engine.evaluate(self.rows())

    def reset_label(self, w):
        pass

    def predupe(self, w):
        # MainWindow calls this while typing as well as when leaving the call.
        # Showing history here must not fill an unfinished callsign's exchange.
        self.populate_history_info_line(w)

    def on_focus_changed(self, w, focused_widget):
        was_callsign = self._callsign_had_focus
        self._callsign_had_focus = focused_widget is w.callsign
        if was_callsign and focused_widget in self.widgets.values():
            self.check_call_history(w)

    def _history_record(self, w):
        call = w.callsign.text().strip().upper()
        if call != self._history_call:
            for col, value in self._history_prefilled.items():
                widget = self.widgets.get(col)
                if widget is not None and widget.text() == value:
                    widget.clear()
            self._history_prefilled = {}
            self._history_call = call
        if not getattr(w, "use_call_history", False) or not call:
            return {}
        return self.database.fetch_call_history(call) or {}

    def populate_history_info_line(self, w):
        record = self._history_record(w)
        if not record:
            w.history_info.clear()
            return
        text = record.get("UserText") or " · ".join(
            dict.fromkeys(
                str(record.get(k) or "").strip()
                for k in ("Exch1", "Loc1", "Sect", "State", "Name")
            )
        ).strip(" ·")
        w.history_info.setText(f"{record['Call']} — {text}")

    def _history_values(self, record):
        """Use the journal's fields and section resources, never its name."""
        sections = self.engine.sections.get(
            self.d.get("multwindowtype", "Section").upper(), {}
        )
        locator_sections = any(
            re.fullmatch(r"[A-R]{2}[0-9]{2}(?:[A-X]{2})?", key) and section == key[:2]
            for key, section in sections.items()
        )
        mapping = {
            "Name": ["Name"],
            "GridSquare": ["Loc1"],
            "Exchange1": ["Exch1"],
            "Sect": ["Sect"],
            "MiscText": ["Misc"],
        }
        if sections:
            mapping["Exchange1"] += ["Sect"]
            mapping["Sect"] += ["Exch1"]
            if locator_sections:
                mapping["Exchange1"] = ["Sect", "Exch1", "Loc1"]
                mapping["Sect"] += ["Loc1"]
            else:
                mapping["Exchange1"] += ["State"]
                mapping["Sect"] += ["State"]
        values = {}
        for col in self.widgets:
            for source in mapping.get(col, ()):
                value = str(record.get(source) or "").strip().upper()
                if (
                    not value
                    or len(value) > self.widgets[col].maxLength()
                    or any(ord(char) < 32 for char in value)
                ):
                    continue
                try:
                    if col == "GridSquare":
                        grid_position(value)
                    elif locator_sections and col in ("Exchange1", "Sect"):
                        # Section files also contain two-letter multiplier aliases;
                        # those and oblast-only hints are not full received areas.
                        if len(value) < 4:
                            continue
                        if value not in sections:
                            grid_position(value)
                            if len(value) == 6 and value[:4] in sections:
                                value = value[:4]
                    elif (
                        col == "Sect"
                        and sections
                        and value not in sections
                        or col == "Exchange1"
                        and source == "State"
                        and value not in sections
                    ):
                        continue
                except UdcError:
                    continue
                values[col] = value
                break
        return values

    def check_call_history(self, w):
        record = self._history_record(w)
        if not record:
            return
        for col, value in self._history_values(record).items():
            widget = self.widgets[col]
            if not widget.text().strip():
                widget.setText(value)
                self._history_prefilled[col] = value
        self.populate_history_info_line(w)

    def prefill(self, w):
        if self.engine is None:
            return
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        freq = float(w.radio_state.get("vfoa", 3500000)) / 1000
        try:
            serial = self.engine.next_serial(self.rows(), now, freq)
        except UdcError:
            return
        w.current_sn = str(serial)
        widget = self.widgets.get("SentNr")
        if widget is not None and widget.text() in ("", self.prefilled_serial):
            self.prefilled_serial = str(serial).zfill(3)
            widget.setText(self.prefilled_serial)

    def set_contact_vars(self, w):
        for col, widget in self.widgets.items():
            w.contact[col] = widget.text().strip().upper()
        for col in ("SNT", "RCV"):
            if col not in self.widgets:
                w.contact[col] = ""

    def validate_contact(self, w):
        if w.pref.get("useserver"):
            raise UdcError("Network Multi-Multi is not supported for UDC journals")
        w.contact["StationPrefix"] = self.engine.station.get("Call", "")
        q = self.engine.normalize(w.contact)
        result = self.engine.evaluate([*self.rows(), q])
        current = next(r for r in result.contacts if r["ID"] == q["ID"])
        w.contact.update({k: v for k, v in current.items() if not k.startswith("_")})
        w.contact_is_dupe = int(current["_dupe"])

    def points(self, w):
        return int(w.contact.get("Points", 0))

    def show_mults(self, w, rtc=None):
        return sum(self.result().multipliers)

    def show_qso(self, w):
        return len(self.rows())

    def calc_score(self, w):
        return self.result().score

    def just_points(self, w):
        return self.result().points

    def get_mults(self, w):
        return {f"mult{i + 1}": v for i, v in enumerate(self.result().multipliers)}

    def recalculate_mults(self, w):
        # Database mutations already rescore all affected rows; this is also an
        # explicit repair path for a journal modified by external SQLite tools.
        rows = self.rows()
        if rows:
            self.database.change_contact(rows[0])

    def specific_contest_check_dupe(self, w, call):
        q = dict(
            w.contact,
            Call=call.upper(),
            TS=datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
            Freq=float(w.radio_state.get("vfoa", 0)) / 1000,
            Mode=mode(w.radio_state.get("mode", "CW")),
        )
        try:
            q["Band"] = band(q["Freq"])[1]
        except UdcError:
            return {"isdupe": 0}
        q.update(
            {col: widget.text().strip().upper() for col, widget in self.widgets.items()}
        )
        if self.engine.version < 3:
            # Keep the version 1/2 entry-window behavior for retained journals.
            from .engine import stamp

            key = self.engine.dupe_key(q)
            limit = self.d.repeat.minutes * 60
            duplicate = any(
                key is not None
                and key == self.engine.dupe_key(r)
                and (
                    not limit
                    or 0 <= (stamp(q["TS"]) - stamp(r["TS"])).total_seconds() < limit
                )
                for r in self.rows()
            )
            return {"isdupe": int(duplicate)}
        return self.engine.duplicate_status(self.rows(), q)

    def refresh_status(self, now=None):
        w = self.window
        if w is None or w.contest is not self or self.status_label is None:
            return
        now = now or datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        rows = self.rows()
        state = self.engine.band_status(rows, now)
        if self.d.repeat.minutes:
            self._repeat_index = self.engine.duplicate_index(rows, now)
            self._repeat_time = now
        text = state.text()
        style = {
            "red": "background-color: #b3261e; color: white;",
            "yellow": "background-color: #ffe082; color: black;",
        }.get(state.severity, "")
        # Recheck the entry as an interval expires, without waiting for a keystroke.
        if w.callsign.text().strip():
            w.check_dupe(w.callsign.text())
            if self.d.repeat.minutes and self.d.repeat.info_status:
                status = self.specific_contest_check_dupe(w, w.callsign.text())
                if status["isdupe"] and status.get("elapsed_minutes") is not None:
                    text += (
                        (" | " if text else "")
                        + f"{w.callsign.text()} worked {status['elapsed_minutes']:.1f} minutes ago"
                    )
        self.status_label.setText(text)
        self.status_label.setStyleSheet(style)
        self.status_label.setToolTip(
            "\n".join(message for _, message in state.warnings)
        )
        self.status_label.setVisible(bool(text))

    def bandmap_repeat(self, call, frequency, comment):
        """Use the same interval decision for spot colours, with one shared index."""
        w = self.window
        if w is None or w.contest is not self:
            return False
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        if self._repeat_time != now:
            self._repeat_index = self.engine.duplicate_index(self.rows(), now)
            self._repeat_time = now
        spot_mode = re.search(
            r"\b(FT8|FT4|RTTY|PSK|CW|SSB|USB|LSB|FM|AM)\b", comment.upper()
        )
        try:
            q = {
                "Call": call.upper(),
                "TS": now,
                "Band": band(frequency)[1],
                "Mode": mode(
                    spot_mode[0] if spot_mode else w.radio_state.get("mode", "CW")
                ),
            }
            return bool(
                self.engine.duplicate_status((), q, self._repeat_index)["isdupe"]
            )
        except UdcError:
            return False

    def ft8_handler(self, record):
        """WSJT-X/fldigi logging without replacing the operator's current entry."""
        w = self.window
        if w is None or w.contest is not self:
            return False
        try:
            if w.pref.get("useserver"):
                raise UdcError("Network Multi-Multi is not supported for UDC journals")
            if self.engine.version < 3:
                raise UdcError("UDP logging requires a new journal using UDC engine 3")
            station = record.get("STATION_CALLSIGN", "").strip().upper()
            if station and station != self.engine.station.get("Call", "").upper():
                raise UdcError("UDP station callsign does not match this journal")
            q = export.contact_from_adif(self.engine, record)
            # Deterministic delivery identity persists across restart. Actual
            # repeated QSOs with a different timestamp remain in the journal.
            identity = json.dumps(dict(record), sort_keys=True, ensure_ascii=False)
            scope = f"{self.d.identifier}/{self.engine.settings['ContestNR']}"
            q["ID"] = uuid.uuid5(
                uuid.NAMESPACE_URL, scope + "/udp-adif/" + identity
            ).hex
            if self.database.conn.execute(
                "SELECT 1 FROM DXLOG WHERE ContestNR=? AND ID=?",
                (q["ContestNR"], q["ID"]),
            ).fetchone():
                return False
            if "SentNr" in self.widgets and not q.get("SentNr"):
                q["SentNr"] = self.engine.next_serial(self.rows(), q["TS"], q["Freq"])
            q.update(
                Operator=w.pref.get("current_op", ""), QSXFreq=q["Freq"], IsOriginal=1
            )
            self.database.log_contact(q)
        except (UdcError, ValueError, TypeError, sqlite3.Error) as exc:
            w.show_message_box(str(exc))
            return False
        result = self.result()
        w.score.setText(str(result.score))
        w.mults.setText(f"{len(result.contacts)}/{sum(result.multipliers)}")
        w.worked_list = self.database.get_calls_and_bands()
        w.send_worked_list()
        w.update_rtc_xml()
        self.prefill(w)
        for dock in (
            w.log_window,
            w.check_window,
            w.statistics_window,
            w.dxcc_window,
            w.zone_window,
            w.rate_window,
        ):
            if dock:
                dock.msg_from_main({"cmd": "UPDATELOG"})
        self.refresh_status()
        return True

    def band_frequency(self, w, band_name, md, default):
        # 3650 is inside all common 80 m phone allocations, unlike 3970.
        return "3650" if (band_name, md) == ("80m", "SSB") else default

    def macro_directory(self, w):
        database_id = hashlib.sha256(
            str(Path(self.database.database).resolve()).encode()
        ).hexdigest()[:12]
        return f"udc-{self.d.identifier[4:]}-{database_id}-{w.pref.get('contest')}"

    def cabrillo(self, w, file_encoding):
        self.save_export(
            w, "log", export.cabrillo(self.engine, self.rows()), file_encoding
        )

    def adif(self, w):
        self.save_export(w, "adi", export.adif(self.engine, self.rows()), "utf-8")

    def save_export(self, w, extension, text, encoding):
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            w, "Export log", f"{self.cabrillo_name}.{extension}", f"Log (*.{extension})"
        )
        if filename:
            try:
                Path(filename).write_bytes(text.encode(encoding))
            except (OSError, UnicodeError) as exc:
                w.show_message_box(str(exc))

    def imp_adif(self, w):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            w, "Import ADIF", "", "ADIF (*.adi *.adif)"
        )
        if not filename:
            return
        try:
            contacts = export.import_adif(
                self.engine, Path(filename).read_text(encoding="utf-8")
            )
            self.engine.evaluate([*self.rows(), *contacts])
            # SAVEPOINT allows all records to roll back, including rescoring, on an
            # invalid/duplicate primary key anywhere in the incoming file.
            from .storage import insert_batch

            insert_batch(self.database, contacts)
        except (UdcError, OSError, sqlite3.Error) as exc:
            w.show_message_box(str(exc))
            return
        w.clearinputs()
        if w.log_window:
            w.log_window.msg_from_main({"cmd": "UPDATELOG"})
