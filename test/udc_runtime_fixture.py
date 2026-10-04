"""Standalone test definitions and UDP packets; no pytest runtime dependency."""

import json
import struct

from not1mm.udc.engine import Engine
from not1mm.udc.model import parse
from not1mm.udc.storage import Bundle

GEO = {
    p: {"primary_pfx": p, "continent": c, "cq": z, "itu": i}
    for p, c, z, i in [("RA", "EU", 16, 29), ("DL", "EU", 14, 28), ("K", "NA", 5, 8)]
}
STATION = {"Call": "RA3VLD", "GridSquare": "KO85"}
SETTINGS = {
    "ContestNR": 1,
    "StartDate": "2027-04-02 16:00:00",
    "OperatorCategory": "SINGLE-OP",
    "SentExchange": "# KO85",
    "ModeCategory": "SSB+CW+DIGITAL",
}


def definition(version=3, **options):
    rules = {
        "Name": "RUNTIME",
        "DisplayName": "Runtime rules",
        "Mode": "BOTH",
        "DupeType": 3,
        "EntryWindowInfo": "SNTText,450,RCVText,450,GridSquareText,600",
        "FrameText": "Snt Rcv Grid",
        "QsoErrorString": "Grid",
        "NumMults": 1,
        "MultSqlString": "Grid",
        "IsMultPer": 3,
        "PointsPerContact": 1,
        "CabrilloVersion": "3.0",
        "CabrilloFormat": 99,
        "CabrilloString": "SNT,4,CallSign,13,RCV,4,GridSquare,6",
    }
    rules.update(options)
    data = "[Author]\nCallsign=RA3VLD\n[Contest]\n" + "\n".join(
        f"{k}={v}" for k, v in rules.items()
    )
    return parse(data.encode(), engine_version=version)


def engine(version=3, settings=None, **rules):
    return Engine(
        definition(version, **rules),
        {},
        STATION,
        settings or SETTINGS,
        GEO,
        engine_version=version,
    )


def qso(time="16:00:00", **fields):
    q = {
        "TS": "2027-04-02 " + time,
        "ID": time,
        "Call": "DL1AAA",
        "Freq": 3650,
        "Mode": "CW",
        "SNT": "599",
        "RCV": "599",
        "GridSquare": "JO62",
        "ContestNR": 1,
        "SentNr": 1,
    }
    q.update(fields)
    return q


def bundle(d, version=3):
    return Bundle(
        "runtime.udc",
        d,
        {"cty.json": json.dumps(GEO).encode()},
        "cty.json",
        engine_version=version,
    )


def udp_packet(record, instance=b"WSJT-X", schema=3):
    text = "".join(f"<{k}:{len(v)}>{v}" for k, v in record.items()) + "<EOR>"
    data = text.encode()
    return (
        struct.pack(">IIII", 0xADBCCBDA, schema, 12, len(instance))
        + instance
        + struct.pack(">I", len(data))
        + data
    )
