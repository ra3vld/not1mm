"""Strict, lossless UDC reader and executable compatibility contract."""

from __future__ import annotations

import configparser
import hashlib
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from types import MappingProxyType


class UdcError(ValueError):
    """An unsupported definition or invalid contact (safe to show to the operator)."""


FIELDS = {
    "snttext": "SNT",
    "rcvtext": "RCV",
    "sntnrtext": "SentNr",
    "rcvnrtext": "NR",
    "exchange1text": "Exchange1",
    "gridsquaretext": "GridSquare",
    "misctext": "MiscText",
    "secttext": "Sect",
    "nametext": "Name",
    "commenttext": "Comment",
}
TOKENS = {
    "snt": "SNT",
    "rcv": "RCV",
    "sentnr": "SentNr",
    "rcvnr": "NR",
    "callsign": "Call",
    "comment": "Comment",
    "gridsquare": "GridSquare",
    "exchange1": "Exchange1",
    "name": "Name",
    "misc": "MiscText",
    "sect": "Sect",
}
MULTS = {
    "N/A",
    "COUNTRYPREFIX",
    "SECTION",
    "WPXPREFIX",
    "GRID",
    "SGRID",
    "FIELD",
    "CALLSIGN",
    "FIRSTQSO",
    "MISC",
    "EXCHANGE",
    "CQZONE",
    "IARUZONE",
    "2LPREFIX",
    "LASTLETTER",
    "EU_COUNTRY",
    "AS_COUNTRY",
    "NA_COUNTRY",
    "SA_COUNTRY",
    "AF_COUNTRY",
    "OC_COUNTRY",
}
# These describe presentation / N1MM's printed summary, not the QSO calculation.
METADATA = {
    "name",
    "displayname",
    "cabrilloname",
    "multiplier1name",
    "multiplier2name",
    "multiplier3name",
    "frametext",
    "loginfo",
    "defaultcontestexchange",
    "specialinstructions",
    "webaddress",
    "scoresummarymultnames",
    "genericprintstring",
    "genericprintstringheader",
    "overlaycategory",
    "period",
}
BAND_CHANGE_OPTIONS = {
    "singleopcountablebandchange",
    "multiopcountablebandchange",
    "countbandormodechange",
    "sobandchangecountmax",
    "mobandchangecountmax",
    "countbandchangespercontest",
    "countbandchangesperperiod",
    "sobandchangetimerduration",
    "mobandchangetimerduration",
    "bandchangesperperiod",
}
SUPPORTED = BAND_CHANGE_OPTIONS | {
    "mode",
    "startofcontest",
    "endofcontest",
    "minimumofftime",
    "multiplierbands",
    "dupetype",
    "pointspercontact",
    "pointsmultbyband",
    "pointsmultbymode",
    "pointsmultbycontinent",
    "pointsmultbycountry",
    "pointsmultbycategory",
    "pointsmultattimegmt",
    "pointmultattimegmt",
    "zonetype",
    "multwindowtype",
    "ismultper",
    "ismult1per",
    "ismult2per",
    "ismult3per",
    "nummults",
    "bonuspoints",
    "bonuspoints2",
    "qsoerrorstring",
    "entrywindowinfo",
    "cabrilloversion",
    "cabrilloformat",
    "cabrillostring",
    "isworkable",
    "dupesqlstring",
    "qsonumbersbyband",
    "multiplesessions",
    "resetmultseverysession",
    "resetsneverysession",
    "dupeqsominutesago",
    "digitalmodesqlstring",
    "showcmycountrystations",
    "showmycountrystations",
    "showwarcbands",
    "cqzonemultcontest",
}
for suffix in ("", "2", "3"):
    SUPPORTED.update(
        k + suffix
        for k in (
            "multsqlstring",
            "donotcountmeasmult",
            "countmultonlyfor",
            "donotcountmultonlyfor",
            "countmultonlyforsec",
            "multmult",
        )
    )
INACTIVE = {"", "0", "false", "no", "n/a"}


def decode(data: bytes, encoding: str | None = None) -> str:
    if len(data) > 8_000_000:
        raise UdcError("File exceeds 8 MB")
    if data.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        encoding = "utf-32"
    elif data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    try:
        return data.decode(encoding or "utf-8-sig")
    except (UnicodeError, LookupError) as exc:
        raise UdcError(
            "Cannot decode file; select its original encoding explicitly"
        ) from exc


def csv(value: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in value.rstrip(", ").split(",") if x.strip())


def pairs(value: str, key: str) -> tuple[tuple[str, str], ...]:
    items = csv(value)
    if len(items) % 2:
        raise UdcError(f"{key}: expected name, value pairs: {value}")
    return tuple(zip(items[::2], items[1::2]))


@dataclass(frozen=True)
class Field:
    token: str
    column: str
    label: str
    width: int


@dataclass(frozen=True)
class WeeklyTime:
    # N1MM numbers Saturday=1 through Friday=7; Python numbers Monday=0.
    day: int
    minutes: int

    @property
    def weekday(self):
        return (self.day + 4) % 7

    def describe(self):
        days = ("Sat", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri")
        return (
            f"{days[self.day - 1]} {self.minutes // 60:02}:{self.minutes % 60:02} UTC"
        )


def weekly_time(value, key):
    if not value:
        return None
    parts = value.split(",")
    try:
        if len(parts) != 2 or not parts[0].strip().isdigit():
            raise ValueError()
        day = int(parts[0])
        if not re.fullmatch(r"\d{1,2}(?:\.\d{1,6})?", parts[1].strip()):
            raise ValueError()
        minutes = Decimal(parts[1].strip()) * 60
        if not 1 <= day <= 7 or not minutes.is_finite() or not 0 <= minutes < 1440:
            raise ValueError()
        if minutes != minutes.to_integral_value():
            raise ValueError()
    except (ValueError, InvalidOperation) as exc:
        raise UdcError(
            f"{key}: expected day 1..7 (Saturday=1), UTC hours 0..<24 in whole minutes"
        ) from exc
    return WeeklyTime(day, int(minutes))


@dataclass(frozen=True)
class RepeatRule:
    minutes: float = 0
    compare_seconds: bool = True
    ignore_band: bool = False
    info_status: bool = True
    this_mode: bool = False
    extended: bool = False


def repeat_rule(value, engine_version=3):
    if not value:
        return RepeatRule()
    parts = value.split(",")
    if len(parts) not in ((1, 5) if engine_version >= 3 else (1,)):
        raise UdcError(
            "DupeQSOMinutesAgo: expected minutes or minutes, CompareToSecond, IgnoreBand, InfoStatus, ThisMode"
        )
    try:
        minutes = float(parts[0])
        if not math.isfinite(minutes * 60) or minutes < 0:
            raise ValueError()
    except ValueError as exc:
        raise UdcError("DupeQSOMinutesAgo must be finite non-negative minutes") from exc
    flags = []
    for flag in parts[1:]:
        if flag.strip().lower() not in ("true", "false", "1", "0", "yes", "no"):
            raise UdcError("DupeQSOMinutesAgo flags must be boolean")
        flags.append(flag.strip().lower() in ("true", "1", "yes"))
    return RepeatRule(minutes, *flags, extended=True) if flags else RepeatRule(minutes)


@dataclass(frozen=True)
class Definition:
    original: bytes
    encoding: str | None
    options: Mapping[str, str]
    author: Mapping[str, str]
    revision: str
    fields: tuple[Field, ...]
    dependencies: tuple[str, ...]
    start: WeeklyTime | None = None
    end: WeeklyTime | None = None
    repeat: RepeatRule = RepeatRule()

    def get(self, key: str, default: str = "") -> str:
        return self.options.get(key.lower(), "") or default

    def integer(self, key: str, default: int = 0) -> int:
        return int(self.get(key, str(default)))

    def flag(self, key: str) -> bool:
        return self.get(key).lower() in ("1", "true", "yes")

    @property
    def identifier(self) -> str:
        # Revision/display-name changes do not alter identity. Builtins use another namespace.
        identity = (
            self.get("name").upper() + "\0" + self.author.get("callsign", "").upper()
        )
        return "udc:" + hashlib.sha256(identity.encode()).hexdigest()[:24]

    @property
    def label(self) -> str:
        return self.get("displayname", self.get("name"))


def parse(
    data: bytes, encoding: str | None = None, engine_version: int | None = None
) -> Definition:
    from . import ENGINE_VERSION

    engine_version = ENGINE_VERSION if engine_version is None else engine_version
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        parser.read_string(decode(data, encoding))
    except configparser.Error as exc:
        raise UdcError(f"Invalid UDC: {exc}") from exc
    if "Contest" not in parser:
        raise UdcError("Missing [Contest] section")
    if any(s not in ("Author", "File", "Contest") for s in parser.sections()):
        raise UdcError("Unsupported section (only Author, File, Contest are supported)")
    opts = {k.lower(): v.strip() for k, v in parser["Contest"].items()}
    supported = (
        SUPPORTED
        if engine_version != 1
        else SUPPORTED
        - {"startofcontest", "endofcontest", "minimumofftime", "multiplierbands"}
    )
    if engine_version < 3:
        supported = supported - BAND_CHANGE_OPTIONS
    for k, v in opts.items():
        if k not in METADATA | supported and v.lower() not in INACTIVE:
            raise UdcError(f"{k}={v}: active rule is not supported by this engine")

    def val(k, default=""):
        return opts.get(k.lower(), "") or default

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", val("name")):
        raise UdcError("Name must contain 1–64 letters, digits, underscore or hyphen")
    for k, allowed, default in [
        ("mode", {"CW", "SSB", "BOTH", "RTTY"}, "CW"),
        ("cabrilloversion", {"2.0", "3.0"}, "2.0"),
        ("cabrilloformat", {"1", "99"}, "1"),
        ("zonetype", {"CQ", "IARU"}, "CQ"),
    ]:
        if val(k, default).upper() not in allowed:
            raise UdcError(f"{k}={val(k)}: unsupported value")
    for k, lo, hi, default in [
        ("multiplierbands", 1, 4, 1),
        ("minimumofftime", 0, 10080, 30),
        ("dupetype", 1, 4, 2),
        ("dupesqlstring", 0, 4, 0),
        ("nummults", 0, 3, 1),
        ("ismultper", 0, 4, 0),
        ("ismult1per", 0, 4, 0),
        ("ismult2per", 0, 4, 0),
        ("ismult3per", 0, 4, 0),
        ("qsonumbersbyband", 0, 2, 0),
    ]:
        try:
            n = int(val(k, str(default)))
        except ValueError as exc:
            raise UdcError(f"{k}: expected integer") from exc
        if not lo <= n <= hi:
            raise UdcError(f"{k}: expected {lo}..{hi}")
    bools = [
        "resetmultseverysession",
        "resetsneverysession",
        "digitalmodesqlstring",
        "showmycountrystations",
        "showwarcbands",
        "cqzonemultcontest",
    ]
    for suffix in ("", "2", "3"):
        bools += ["donotcountmeasmult" + suffix, "multmult" + suffix]
        if val("multsqlstring" + suffix, "N/A").upper() not in MULTS:
            raise UdcError(
                f"MultSqlString{suffix}={val('multsqlstring' + suffix)}: unsupported selector"
            )
    if engine_version >= 3:
        bools += [
            "singleopcountablebandchange",
            "multiopcountablebandchange",
            "countbandormodechange",
            "countbandchangespercontest",
            "countbandchangesperperiod",
        ]
        for key in (
            "sobandchangecountmax",
            "mobandchangecountmax",
            "sobandchangetimerduration",
            "mobandchangetimerduration",
            "bandchangesperperiod",
        ):
            if val(key) and (
                not re.fullmatch(r"\d+", val(key)) or int(val(key)) > 2147483647
            ):
                raise UdcError(f"{key}: expected integer 0..2147483647")
        if val("countbandchangespercontest").lower() in ("true", "1", "yes") and val(
            "countbandchangesperperiod"
        ).lower() in ("true", "1", "yes"):
            raise UdcError("Band changes: choose per contest or per period, not both")
    for k in bools:
        if val(k).lower() not in {"", "0", "1", "true", "false", "yes", "no"}:
            raise UdcError(f"{k}: expected boolean")
    session = val("multiplesessions")
    if session:
        if not re.fullmatch(r"\d{4}/\d{1,4}", session):
            raise UdcError("MultipleSessions: expected HHMM/HHMM")
        start, length = map(int, session.split("/"))
        if start // 100 > 23 or start % 100 > 59 or length % 100 > 59 or length == 0:
            raise UdcError("MultipleSessions: invalid time/duration")
    repeat = repeat_rule(val("dupeqsominutesago"), engine_version)
    labels = val("frametext").split()
    fields = []
    for i, (token, width) in enumerate(
        pairs(val("entrywindowinfo"), "EntryWindowInfo")
    ):
        if token.lower() not in FIELDS:
            raise UdcError(f"EntryWindowInfo: unsupported field {token}")
        if not width.isdigit() or not 1 <= int(width) <= 10000:
            raise UdcError(f"EntryWindowInfo: invalid width {width}")
        fields.append(
            Field(
                token.lower(),
                FIELDS[token.lower()],
                labels[i] if i < len(labels) else FIELDS[token.lower()],
                int(width),
            )
        )
    if not fields or len({f.column for f in fields}) != len(fields):
        raise UdcError("EntryWindowInfo must contain unique fields")
    for token, width in pairs(val("cabrillostring"), "CabrilloString"):
        if token.lower() not in TOKENS and token.lower() not in {
            "sentexch",
            "sentexchpart1",
            "sentexchpart2",
            "sentexchpart3",
        }:
            raise UdcError(f"CabrilloString: unsupported token {token}")
        if not width.isdigit() or not 1 <= int(width) <= 200:
            raise UdcError(f"CabrilloString: invalid width {width}")
    if val("cabrilloformat") == "99" and not val("cabrillostring"):
        raise UdcError("CabrilloFormat=99 requires CabrilloString")
    log_fields = {
        "SentReport",
        "ReceiveReport",
        "SentNR",
        "SentNr",
        "NR",
        "Exchange1",
        "GridSquare",
        "MiscText",
        "Sect",
        "Name",
        "Comment",
        "IsMultiplier1",
        "IsMultiplier2",
        "IsMultiplier3",
        "Points",
        "ZN",
        "WPX",
        "Power",
        "Operator",
    }
    for token, width in pairs(val("loginfo"), "LogInfo"):
        if token not in log_fields or not width.isdigit():
            raise UdcError(f"LogInfo: unsupported column/width {token}, {width}")
    if val("showmycountrystations").lower() in ("false", "0"):
        raise UdcError(
            "ShowMyCountryStations=False: bandmap filtering is not supported"
        )
    if val("cqzonemultcontest").lower() in ("true", "1") and not any(
        val("multsqlstring" + s).upper() == "CQZONE" for s in ("", "2", "3")
    ):
        raise UdcError(
            "CQZoneMultContest requires an explicit CQZONE multiplier selector"
        )
    deps = []
    if any(val("multsqlstring" + s).upper() == "SECTION" for s in ("", "2", "3")):
        deps.append(val("multwindowtype", "Section") + ".sec")
    for check in csv(val("qsoerrorstring")):
        check = re.sub(
            r"^(?:" + "|".join(FIELDS) + r")_", "", check, flags=re.IGNORECASE
        )
        base = re.sub(r"_or_empty$", "", check, flags=re.IGNORECASE)
        if base.lower() not in (
            "any",
            "any_not_empty",
            "numeric",
            "numeric_not_empty",
            "grid",
        ):
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", base):
                raise UdcError(f"QsoErrorString: unsupported check {check}")
            deps.append(base + ".sec")
    if val("bonuspoints2"):
        parts = csv(val("bonuspoints2"))
        if len(parts) != 2:
            raise UdcError("BonusPoints2: expected points, filename")
        deps.append(parts[1])
    if any(not re.fullmatch(r"[A-Za-z0-9_.-]+", d) or d.startswith(".") for d in deps):
        raise UdcError("Dependency names must be plain filenames")
    definition = Definition(
        data,
        encoding,
        MappingProxyType(opts),
        MappingProxyType(dict(parser["Author"]) if "Author" in parser else {}),
        parser.get("File", "Revision", fallback=""),
        tuple(fields),
        tuple(dict.fromkeys(deps)),
        weekly_time(val("startofcontest"), "StartOfContest"),
        weekly_time(val("endofcontest"), "EndOfContest"),
        repeat,
    )
    from .engine import validate_rules

    validate_rules(definition)
    return definition
