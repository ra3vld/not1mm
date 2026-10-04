"""Hand-calculated boundaries for engine 3; no external network/geography needed."""

import itertools
import struct

import pytest
from udc_runtime_fixture import (
    SETTINGS,
    STATION,
    bundle,
    definition,
    engine,
    qso,
    udp_packet,
)

from not1mm import fsutils
from not1mm.lib.database import DataBase
from not1mm.lib.ft8_watcher import FT8Watcher
from not1mm.udc.export import adif, cabrillo, contact_from_adif, import_adif
from not1mm.udc.model import UdcError
from not1mm.udc.storage import create_journal, engine_for


@pytest.mark.parametrize(
    "compare,ignore,info,same", list(itertools.product((True, False), repeat=4))
)
def test_extended_repeat_flags(compare, ignore, info, same):
    e = engine(DupeType=4, DupeQSOMinutesAgo=f"10,{compare},{ignore},{info},{same}")
    a, b = qso(), qso("16:01:00", Freq=7074, Mode="SSB")
    expected = ignore and not same
    assert e.evaluate([a, b]).contacts[1]["_dupe"] is expected
    assert e.duplicate_status([a], e.normalize(b))["isdupe"] == expected
    assert e.d.repeat.info_status is info


@pytest.mark.parametrize("seconds,expected", [(True, True), (False, False)])
def test_minute_comparison_discards_seconds(seconds, expected):
    e = engine(DupeType=4, DupeQSOMinutesAgo=f"10,{seconds},False,True,False")
    a, b = qso("16:00:59"), qso("16:10:00")
    assert e.evaluate([a, b]).contacts[1]["_dupe"] is expected
    assert e.duplicate_status([a], e.normalize(b))["isdupe"] == expected


def test_scalar_anchor_extended_anchor_and_preview_agree():
    rows = [qso(t) for t in ("16:00:00", "16:05:00", "16:10:00", "16:20:00")]
    for rule, expected in [
        ("10", [False, True, False, False]),
        ("10,True,False,True,False", [False, True, True, False]),
    ]:
        e = engine(DupeQSOMinutesAgo=rule)
        result = e.evaluate(rows)
        assert [q["_dupe"] for q in result.contacts] == expected
        for i, q in enumerate(rows):
            assert e.duplicate_status(rows[:i], e.normalize(q))["isdupe"] == expected[i]
        assert e.duplicate_status(rows[1:], e.normalize(rows[0]))["isdupe"] == 0
        assert cabrillo(e, rows).count("QSO:") == 4
        assert e.evaluate(import_adif(e, adif(e, rows))).score == result.score


@pytest.mark.parametrize(
    "value",
    [
        "nan",
        "inf",
        "-1",
        "10,True",
        "10,nope,False,True,False",
        "10,True,False,True,False,True",
    ],
)
def test_invalid_repeat_rules(value):
    with pytest.raises(UdcError):
        definition(DupeQSOMinutesAgo=value)


def test_zero_interval_and_session_boundary():
    e = engine(DupeType=4, DupeQSOMinutesAgo="0,False,True,True,False")
    assert not e.evaluate([qso(), qso("16:00:01")]).contacts[1]["_dupe"]
    e = engine(
        DupeType=4,
        MultipleSessions="1600/30",
        DupeQSOMinutesAgo="60,True,True,True,False",
    )
    assert not e.evaluate([qso("16:29:59"), qso("16:30:00")]).contacts[1]["_dupe"]


def test_band_counters_hour_boundaries_timer_and_modes():
    e = engine(
        SingleOpCountableBandChange=True,
        SOBandChangeCountMax=2,
        CountBandOrModeChange=True,
        SOBandChangeTimerDuration=10,
    )
    rows = [
        qso("16:58:00"),
        qso("16:59:00", Mode="SSB"),
        qso("17:00:00", Freq=7074, Mode="SSB"),
        qso("17:01:00", Freq=7074),
        qso("17:02:00", Freq=3650),
    ]
    assert e.band_status(rows, "2027-04-02 16:58:00").remaining_seconds == 600
    assert e.band_status(rows, "2027-04-02 16:59:00").count == 1
    assert e.band_status(rows, "2027-04-02 17:00:00").count == 1
    state = e.band_status(rows, "2027-04-02 17:02:00")
    assert (state.count, state.severity, state.remaining_seconds) == (3, "red", 600)
    assert len(state.warnings) == 3  # two early band changes and one count violation
    assert e.band_status(rows, "2027-04-02 17:12:00").remaining_seconds == 0
    assert e.band_status(rows, "2027-04-02 18:00:00").count == 0
    # Warnings never remove a QSO or change scoring.
    assert e.evaluate(rows) == engine().evaluate(rows)


def test_counter_scopes_categories_and_radios():
    rows = [qso("16:29:00"), qso("16:30:00", Freq=7074), qso("16:31:00", Freq=3650)]
    rules = {
        "SingleOpCountableBandChange": True,
        "SOBandChangeCountMax": 2,
        "MultiOpCountableBandChange": True,
        "MOBandChangeCountMax": 5,
        "MultipleSessions": "1600/30",
    }
    e = engine(**rules, CountBandChangesPerPeriod=True)
    assert e.band_status(rows, "2027-04-02 16:31:00").count == 2
    assert e.band_status(rows, "2027-04-02 17:00:00").count == 0
    e = engine(**rules, CountBandChangesPerContest=True)
    assert e.band_status(rows, "2027-04-03 00:00:00").count == 2
    e = engine(settings=dict(SETTINGS, OperatorCategory="MULTI-OP"), **rules)
    assert e.band_status(rows, "2027-04-02 16:31:00").maximum == 5
    assert (
        engine(**rules)
        .band_status(
            [dict(q, RadioNR=i + 1) for i, q in enumerate(rows)], "2027-04-02 17:00:00"
        )
        .count
        == 0
    )
    assert (
        engine(BandChangesPerPeriod=4).band_status(rows, "2027-04-02 17:00:00").count
        == 2
    )


@pytest.mark.parametrize(
    "rules",
    [
        {"SOBandChangeCountMax": -1},
        {"MOBandChangeTimerDuration": "1.5"},
        {"CountBandChangesPerPeriod": True, "CountBandChangesPerContest": True},
        {"SingleOpCountableBandChange": "bad"},
    ],
)
def test_invalid_band_rules(rules):
    with pytest.raises(UdcError):
        definition(**rules)


def test_ft_points_dupes_mults_exports_and_standard_adif():
    e = engine(PointsPerContact="FT8,2,FT4,3,DIGI,4,CW,1")
    rows = [
        qso(Mode="FT8", SNT="-10", RCV="+03"),
        qso("16:00:30", Mode="FT4", SNT="-12", RCV="-05"),
        qso("16:01:00", Mode="FT8"),
        qso("16:02:00", Mode="FT8", Freq=7074),
        qso("16:03:00", Mode="RTTY"),
    ]
    result = e.evaluate(rows)
    assert (result.points, result.multipliers, result.score) == (11, (4, 0, 0), 44)
    assert [q["Points"] for q in result.contacts] == [2, 3, 0, 2, 4]
    assert "<MODE:4>MFSK" in adif(e, rows)
    assert "<SUBMODE:3>FT4" in adif(e, rows)
    restored = import_adif(e, adif(e, rows))
    assert e.evaluate(restored).score == 44
    assert [q["Mode"] for q in restored] == ["FT8", "FT4", "FT8", "FT8", "RTTY"]
    assert restored[0]["SNT"] == "-10"
    assert restored[0]["RCV"] == "+03"
    assert cabrillo(e, rows).count(" DG ") == 4
    assert len(result.contacts) == 5


def test_digi_factor_covers_ft_and_rtty_psk():
    e = engine(PointsMultByMode="DIGI,2")
    for md in ("FT8", "FT4", "RTTY", "PSK"):
        assert e.evaluate([qso(Mode=md)]).points == 2
    assert e.evaluate([qso()]).points == 1
    # Existing DigitalModeSqlString is specifically RTTY + PSK, not all digital modes.
    e = engine(DigitalModeSqlString=True)
    assert e.mode_key(qso(Mode="RTTY")) == e.mode_key(qso(Mode="PSK"))
    assert e.mode_key(qso(Mode="FT8")) != e.mode_key(qso(Mode="FT4"))


def test_protocol_fields_before_call_queued_truncated_and_optional_fields():
    record = {
        "QSO_DATE": "20270402",
        "TIME_ON": "160000",
        "MODE": "MFSK",
        "SUBMODE": "FT4",
        "CALL": "DL1AAA",
        "FREQ": "3.573",
        "GRIDSQUARE": "JO62",
        "RST_SENT": "-10",
        "RST_RCVD": "-05",
    }
    packet = udp_packet(record)
    assert FT8Watcher.logged_adif(packet) == record
    assert FT8Watcher.logged_adif(packet + b"future fields") == record
    assert contact_from_adif(engine(), FT8Watcher.logged_adif(packet))["Mode"] == "FT4"
    for data in (
        b"",
        b"bad",
        packet[:15],
        packet[:-1],
        packet.replace(b"\xad\xbc\xcb\xda", b"xxxx"),
        packet[:12] + struct.pack(">I", 0xFFFFFFFF),
    ):
        assert FT8Watcher.logged_adif(data) is None


def test_edit_delete_restart_and_old_snapshots(tmp_path):
    db = DataBase(tmp_path / "rules.db", fsutils.APP_DATA_PATH, 1)
    rules = {
        "DupeType": 4,
        "DupeQSOMinutesAgo": "10,True,False,True,False",
        "SingleOpCountableBandChange": True,
        "SOBandChangeCountMax": 2,
        "SOBandChangeTimerDuration": 10,
    }
    create_journal(
        db,
        dict(SETTINGS, ContestName=definition(**rules).identifier),
        bundle(definition(**rules)),
        STATION,
    )
    for q in [qso(), qso("16:05:00", Freq=7074), qso("16:10:00")]:
        db.log_contact(dict(db.empty_contact, **q))
    e = engine_for(db, 1)
    assert [q["Points"] for q in db.fetch_all_contacts_asc()] == [1, 1, 1]
    q = db.fetch_all_contacts_asc()[1]
    db.change_contact(dict(q, Freq=3650))
    assert [q["Points"] for q in db.fetch_all_contacts_asc()] == [1, 0, 0]
    assert e.band_status(db.fetch_all_contacts_asc(), "2027-04-02 16:10:00").count == 0
    db.delete_contact(q["ID"])
    assert [q["Points"] for q in db.fetch_all_contacts_asc()] == [1, 1]
    for version in (1, 2):
        d = definition(version, PointsPerContact="DIGI,5")
        settings = dict(SETTINGS, ContestNR=version + 1, ContestName=d.identifier)
        create_journal(db, settings, bundle(d, version), STATION)
        assert engine_for(db, version + 1).evaluate([qso(Mode="RTTY")]).points == 1
        with pytest.raises(UdcError):
            engine_for(db, version + 1).normalize(qso(Mode="FT8"))
    db.conn.close()
    db = DataBase(tmp_path / "rules.db", fsutils.APP_DATA_PATH, 1)
    assert engine_for(db, 1).version == 3
    assert engine_for(db, 1).evaluate(db.fetch_all_contacts_asc()).points == 2
    assert engine_for(db, 2).version == 1
    assert engine_for(db, 3).version == 2
    db.conn.close()
