"""Call History uses journal fields, never guessed serials or another entry."""

from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from test_udc_engine import CASES, fixture

from not1mm import fsutils
from not1mm.lib.database import DataBase
from not1mm.udc.plugin import UdcContest


class Text:
    def __init__(self, value=""):
        self.value = value

    def text(self):
        return self.value

    def setText(self, value):
        self.value = value

    def clear(self):
        self.value = ""

    def maxLength(self):
        return 20

    def setAccessibleName(self, value):
        self.accessible = value

    def setFocus(self):
        self.focused = True

    def setVisible(self, value):
        self.visible = value


def adapter(name="VLADIMIR", record=None):
    bundle, station, settings, _ = fixture(name)
    records = {record.get("Call", "R3VL"): record} if record else {}
    database = SimpleNamespace(
        fetch_call_history=lambda call: records.get(call),
        fetch_all_contacts_asc=list,
    )
    plugin = UdcContest(bundle, database, station, settings)
    plugin.widgets = {f.column: Text() for f in plugin.d.fields}
    plugin.labels = {f.column: Text() for f in plugin.d.fields}
    plugin.prefilled_serial = ""
    window = SimpleNamespace(
        callsign=Text("R3VL"),
        history_info=Text(),
        use_call_history=True,
        radio_state={"vfoa": 3500000, "mode": "CW"},
        current_mode="CW",
        check_callsign=lambda _call: None,
        field1=Text(),
        field2=Text(),
        field3=Text(),
        field4=Text(),
    )
    spare = iter((window.field3, window.field4))
    base = {"SNT": window.field1, "RCV": window.field2}
    for field in plugin.d.fields:
        frame = base.get(field.column) or next(spare, None)
        if frame is None:
            frame = Text()
            plugin.extra.append(frame)
        plugin.frames[field.column] = frame
    return plugin, window


def test_typing_shows_district_and_grid_without_filling_exchange():
    p, w = adapter(
        record={
            "Call": "R3VL",
            "Exch1": "VL13",
            "Loc1": "KO96",
            "Sect": "VL13",
            "UserText": "VL13 (KO96)",
        }
    )
    p.predupe(w)
    assert w.history_info.text() == "R3VL — VL13 (KO96)"
    assert all(not field.text() for field in p.widgets.values())
    p.check_call_history(w)
    assert p.widgets["Exchange1"].text() == "VL13"
    assert p.widgets["NR"].text() == ""  # received serial is never guessed
    assert p.widgets["SentNr"].text() == ""


def test_district_wins_over_geographic_exchange_and_grid_fallback():
    p, w = adapter(
        record={"Call": "R3VL", "Exch1": "KO96", "Sect": "VL13", "Loc1": "KO96"}
    )
    p.check_call_history(w)
    assert p.widgets["Exchange1"].text() == "VL13"
    p, w = adapter(record={"Call": "R3VL", "Loc1": "KO96"})
    p.check_call_history(w)
    assert p.widgets["Exchange1"].text() == "KO96"


@pytest.mark.parametrize("area", ["MA", "VL", "NN", "KO", "VL99", "NOT-A-GRID"])
def test_incomplete_or_invalid_location_remains_a_visible_hint(area):
    p, w = adapter(record={"Call": "R3VL", "Exch1": area, "State": area})
    p.check_call_history(w)
    assert p.widgets["Exchange1"].text() == ""
    p.populate_history_info_line(w)
    assert area in w.history_info.text()


def test_tab_fills_location_but_goes_to_received_serial():
    p, w = adapter(record={"Call": "R3VL", "Exch1": "VL13"})
    p.set_tab_next(w)
    p.set_tab_prev(w)
    event = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier
    )
    assert p.key_event(w, w.callsign, event)
    assert p.widgets["Exchange1"].text() == "VL13"
    assert p.widgets["NR"].text() == ""
    assert w.next_field is p.widgets["NR"]
    assert w.next_field.focused


def test_click_leave_fills_without_keyboard_event():
    p, w = adapter(record={"Call": "R3VL", "Exch1": "VL13"})
    p.on_focus_changed(w, w.callsign)
    p.on_focus_changed(w, p.widgets["NR"])
    assert p.widgets["Exchange1"].text() == "VL13"


def test_call_correction_clears_only_values_owned_by_history():
    p, w = adapter(record={"Call": "R3VL", "Exch1": "VL13"})
    p.check_call_history(w)
    p.widgets["NR"].setText("023")
    w.callsign.setText("R3VL/P")  # portable calls are exact independent identities
    p.populate_history_info_line(w)
    assert p.widgets["Exchange1"].text() == ""
    assert p.widgets["NR"].text() == "023"
    assert w.history_info.text() == ""


def test_existing_and_edited_exchange_are_preserved():
    p, w = adapter(record={"Call": "R3VL", "Exch1": "VL13"})
    p.widgets["Exchange1"].setText("KO85")
    p.check_call_history(w)
    assert p.widgets["Exchange1"].text() == "KO85"
    assert not p._history_prefilled
    w.callsign.setText("UNKNOWN")
    p.populate_history_info_line(w)
    assert p.widgets["Exchange1"].text() == "KO85"
    p, w = adapter(record={"Call": "R3VL", "Exch1": "VL13"})
    p.check_call_history(w)
    p.widgets["Exchange1"].setText("KO85")
    w.callsign.setText("UNKNOWN")
    p.populate_history_info_line(w)
    assert p.widgets["Exchange1"].text() == "KO85"


def test_disabled_history_never_fetches_or_fills():
    p, w = adapter(record={"Call": "R3VL", "Exch1": "VL13"})
    w.use_call_history = False
    p.database.fetch_call_history = lambda _call: pytest.fail("history is disabled")
    p.predupe(w)
    p.check_call_history(w)
    assert not p.widgets["Exchange1"].text()


def test_other_udc_grid_field_gets_grid_not_vladimir_district():
    p, w = adapter("RTC", {"Call": "R3VL", "Exch1": "VL13", "Loc1": "KO96"})
    p.check_call_history(w)
    assert p.widgets["GridSquare"].text() == "KO96"


def test_non_locator_sections_still_accept_two_letter_exchange():
    p, w = adapter("KCJ_JA", {"Call": "R3VL", "Exch1": "TK"})
    p.check_call_history(w)
    assert p.widgets["Exchange1"].text() == "TK"


def test_subsquare_uses_the_received_spelling_declared_in_section_resource():
    p, w = adapter(record={"Call": "R3VL", "Loc1": "KO96AB"})
    p.check_call_history(w)
    assert p.widgets["Exchange1"].text() == "KO96"


def test_grid_shaped_identity_sections_do_not_imply_geographic_exchange():
    p, w = adapter("KCJ_JA", {"Call": "R3VL", "Loc1": "KO96"})
    p.engine.sections[p.d.get("multwindowtype").upper()] = {"MA01": "MA01"}
    p.check_call_history(w)
    assert p.widgets["Exchange1"].text() == ""


@pytest.mark.parametrize("name", CASES)
def test_anatomy_contract_labels_and_navigation_do_not_reset_entry(name):
    p, w = adapter(name)
    for required in (
        "init_contest",
        "interface",
        "set_tab_next",
        "set_tab_prev",
        "set_contact_vars",
        "predupe",
        "prefill",
        "points",
        "show_mults",
        "show_qso",
        "just_points",
        "calc_score",
        "adif",
        "cabrillo",
        "recalculate_mults",
        "check_call_history",
        "populate_history_info_line",
    ):
        assert callable(getattr(p, required))
    assert p.name and p.cabrillo_name and p.mode and p.columns and p.dupe_type
    values = {col: f"VALUE-{i}" for i, col in enumerate(p.widgets)}
    for col, value in values.items():
        p.widgets[col].setText(value)
        p.labels[col].setText("translated default")
    p.interface(w)
    p.set_tab_next(w)
    p.set_tab_prev(w)
    assert {col: field.text() for col, field in p.widgets.items()} == values
    for field in p.d.fields:
        assert p.labels[field.column].text() == field.label
        assert p.frames[field.column].visible
    for frame in (w.field1, w.field2, w.field3, w.field4):
        assert frame.visible == (frame in p.frames.values())
    assert w.tab_next[w.callsign] is w.next_field
    assert set(w.tab_prev) == {w.callsign, *p.widgets.values()}


def test_import_validation_keeps_existing_history(tmp_path):
    db = DataBase(tmp_path / "history.db", fsutils.APP_DATA_PATH)
    db.add_callhistory_item({"Call": "OLD", "Loc1": "KO85"})
    for rows in ([], [{"Call": ""}], [{"Call": "NEW", "NotAColumn": "value"}]):
        with pytest.raises(ValueError):
            db.replace_callhistory_items(rows)
        assert db.fetch_call_history("OLD")["Loc1"] == "KO85"
    db.replace_callhistory_items([{"call": "r3vl", "exch1": "VL13"}])
    assert db.fetch_call_history("R3VL")["Exch1"] == "VL13"
    assert not db.fetch_call_history("OLD")
    db.conn.close()


def test_database_failure_rolls_back_whole_import(tmp_path):
    import sqlite3

    db = DataBase(tmp_path / "history.db", fsutils.APP_DATA_PATH)
    db.add_callhistory_item({"Call": "OLD", "Loc1": "KO85"})
    db.conn.execute(
        "CREATE TRIGGER fail_history BEFORE INSERT ON CALLHISTORY "
        "WHEN NEW.Call='FAIL' BEGIN SELECT RAISE(ABORT, 'test failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.replace_callhistory_items([{"Call": "NEW"}, {"Call": "FAIL"}])
    assert db.fetch_call_history("OLD")["Loc1"] == "KO85"
    assert not db.fetch_call_history("NEW")
    db.conn.close()
