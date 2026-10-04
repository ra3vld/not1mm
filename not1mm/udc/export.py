"""Cabrillo and lossless ADIF exchanges from the same evaluated journal."""

from .engine import mode
from .model import TOKENS, UdcError, pairs


def cabrillo(engine, contacts):
    d = engine.d
    settings = engine.settings
    station = engine.station
    result = engine.evaluate(contacts)
    lines = [
        "START-OF-LOG: " + d.get("cabrilloversion", "2.0"),
        "CREATED-BY: not1mm UDC",
        "CONTEST: " + d.get("cabrilloname", d.get("name")),
        "CALLSIGN: " + station.get("Call", ""),
        "CLAIMED-SCORE: " + str(result.score),
    ]
    for key, value in [
        ("OPERATOR", "OperatorCategory"),
        ("BAND", "BandCategory"),
        ("MODE", "ModeCategory"),
        ("POWER", "PowerCategory"),
        ("STATION", "StationCategory"),
        ("ASSISTED", "AssistedCategory"),
        ("TRANSMITTER", "TransmitterCategory"),
    ]:
        if settings.get(value):
            category = settings[value]
            if key == "MODE" and category in ("SSB+CW", "SSB+CW+DIGITAL", "BOTH"):
                category = "MIXED"
            lines.append(f"CATEGORY-{key}: {category}")
    for key, value in [
        ("NAME", "Name"),
        ("EMAIL", "Email"),
        ("GRID-LOCATOR", "GridSquare"),
    ]:
        if station.get(value):
            lines.append(f"{key}: {station[value]}")
    template = d.get(
        "cabrillostring", "SNT, 4, SentNr, 6, CallSign, 13, RCV, 4, RcvNr, 6"
    )
    for q in result.contacts:
        sent = settings.get("SentExchange", "").replace("#", str(q.get("SentNr", "")))
        parts = sent.split()
        values = {"sentexch": sent}
        values.update(
            {
                f"sentexchpart{i + 1}": parts[i] if i < len(parts) else ""
                for i in range(3)
            }
        )
        values.update({token: str(q.get(col, "")) for token, col in TOKENS.items()})
        exchange = "".join(
            values[token.lower()].ljust(int(width)) + " "
            for token, width in pairs(template, "CabrilloString")
        ).rstrip()
        md = {"SSB": "PH", "RTTY": "RY", "FT8": "DG", "FT4": "DG"}.get(
            mode(q["Mode"]), mode(q["Mode"])
        )
        lines.append(
            f"QSO: {round(float(q['Freq'])):5} {md:2} {q['TS'][:10]} {q['TS'][11:16].replace(':', '')} {station.get('Call', ''):<13} {exchange}"
        )
    lines.append("END-OF-LOG:")
    if any("\n" in s or "\r" in s for s in lines):
        raise UdcError("Cabrillo header contains a line break")
    return "\r\n".join(lines) + "\r\n"


ADIF_FIELDS = {
    "CALL": "Call",
    "MODE": "Mode",
    "RST_SENT": "SNT",
    "RST_RCVD": "RCV",
    "STX": "SentNr",
    "SRX": "NR",
    "GRIDSQUARE": "GridSquare",
    "NAME": "Name",
    "COMMENT": "Comment",
    "APP_NOT1MM_EXCHANGE1": "Exchange1",
    "APP_NOT1MM_SECT": "Sect",
    "APP_NOT1MM_MISC": "MiscText",
}


def adif(engine, contacts):
    def field(k, v):
        v = str(v)
        return f"<{k}:{len(v)}>{v}"

    lines = ["<ADIF_VER:5>3.1.4<PROGRAMID:6>not1mm<EOH>"]
    for q in engine.evaluate(contacts).contacts:
        fields = {tag: q.get(col, "") for tag, col in ADIF_FIELDS.items()}
        if q["Mode"] == "FT4":
            fields["MODE"] = "MFSK"
            fields["SUBMODE"] = "FT4"
        fields["APP_NOT1MM_UDC_VERSION"] = "1"
        fields.update(
            QSO_DATE=q["TS"][:10].replace("-", ""),
            TIME_ON=q["TS"][11:].replace(":", ""),
            FREQ=format(float(q["Freq"]) / 1000, ".6f"),
            STATION_CALLSIGN=engine.station.get("Call", ""),
            CONTEST_ID=engine.d.get("cabrilloname", engine.d.get("name")),
            STX_STRING=engine.settings.get("SentExchange", "").replace(
                "#", str(q.get("SentNr", ""))
            ),
            SRX_STRING=" ".join(
                str(q.get(f.column, ""))
                for f in engine.d.fields
                if f.column not in ("SNT", "SentNr", "RCV")
            ),
        )
        lines.append("".join(field(k, v) for k, v in fields.items()) + "<EOR>")
    return "\n".join(lines) + "\n"


def contact_from_adif(engine, record):
    """Decode one ADIF record identically for file imports and WSJT-X."""
    import uuid

    q = {col: record.get(tag, "") for tag, col in ADIF_FIELDS.items()}
    if (
        record.get("MODE", "").upper() == "MFSK"
        and record.get("SUBMODE", "").upper() == "FT4"
    ):
        q["Mode"] = "FT4"
    date = record.get("QSO_DATE", "")
    time = record.get("TIME_ON", "").ljust(6, "0")
    if len(date) != 8 or len(time) != 6:
        raise UdcError("ADIF requires QSO_DATE and TIME_ON")
    q.update(
        TS=f"{date[:4]}-{date[4:6]}-{date[6:]} {time[:2]}:{time[2:4]}:{time[4:]}",
        Freq=float(record.get("FREQ", "0")) * 1000,
        ID=uuid.uuid4().hex,
        ContestNR=engine.settings["ContestNR"],
        StationPrefix=engine.station.get("Call", ""),
        ContestName=engine.d.get("cabrilloname", engine.d.get("name")),
    )
    # Standard SRX_STRING has no RST. Explicit ADIF fields take precedence;
    # ambiguous compound exchanges are rejected rather than guessed.
    tags = {column: tag for tag, column in ADIF_FIELDS.items()}
    missing = [
        f.column
        for f in engine.d.fields
        if f.column not in ("SNT", "RCV", "SentNr") and tags.get(f.column) not in record
    ]
    received = record.get("SRX_STRING", "")
    if missing and received and not record.get("APP_NOT1MM_UDC_VERSION"):
        values = received.split() if len(missing) > 1 else [received]
        if len(values) != len(missing):
            raise UdcError("ADIF SRX_STRING does not match the exchange fields")
        q.update(zip(missing, values))
    return engine.normalize(q)


def import_adif(engine, text):
    import adif_io

    records, _ = adif_io.read_from_string(text)
    return [contact_from_adif(engine, record) for record in records]
