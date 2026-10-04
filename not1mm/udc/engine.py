"""Deterministic UDC evaluation shared by insert, edit, delete and import.

Inputs are plain dictionaries using DXLOG names. Evaluation never changes inputs.
Geography and external resources belong to the journal, not to global state.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from not1mm.lib.ham_utility import calculate_wpx_prefix

from . import ENGINE_VERSION
from .model import FIELDS, Definition, UdcError, csv, decode, pairs
from .sections import parse_sections

BANDS = {
    "160m": (1800, 2000, 1.8),
    "80m": (3500, 4000, 3.5),
    "40m": (7000, 7300, 7),
    "30m": (10100, 10150, 10),
    "20m": (14000, 14350, 14),
    "17m": (18068, 18168, 18),
    "15m": (21000, 21450, 21),
    "12m": (24890, 24990, 24),
    "10m": (28000, 29700, 28),
    "6m": (50000, 54000, 50),
    "4m": (70000, 71000, 70),
    "2m": (144000, 148000, 144),
    "1.25m": (222000, 225000, 222),
    "70cm": (420000, 450000, 420),
    "33cm": (902000, 928000, 902),
    "23cm": (1240000, 1300000, 1240),
    "13cm": (2300000, 2450000, 2300),
    "9cm": (3300000, 3500000, 3300),
}
CONTINENTS = {"EU", "AS", "NA", "SA", "AF", "OC", "AN"}
MODES = {"CW", "SSB", "RTTY", "PSK", "DIGI", "FM", "AM", "USB", "LSB", "FT8", "FT4"}
DIGITAL_MODES = {"RTTY", "PSK", "DIGI", "FT8", "FT4"}


def stamp(value):
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError as exc:
        raise UdcError(f"TS: expected UTC YYYY-MM-DD HH:MM:SS, got {value}") from exc


def mode(value):
    value = str(value).upper()
    if value in ("SSB", "USB", "LSB", "PH"):
        return "SSB"
    if value in ("CW", "CWR", "CW-R", "CW-U", "CW-L"):
        return "CW"
    if value in (
        "RY",
        "RTTY",
        "RTTYR",
        "RTTY-R",
        "DIGI-U",
        "DIGI-L",
        "PKTUSB",
        "PKTLSB",
    ):
        return "RTTY"
    if value.startswith("PSK"):
        return "PSK"
    return value


def band(freq):
    try:
        frequency = float(freq)
    except (TypeError, ValueError) as exc:
        raise UdcError("Freq: expected kHz") from exc
    for name, (low, high, number) in BANDS.items():
        if low <= frequency <= high:
            return name, number
    raise UdcError(f"Freq={freq} kHz is outside supported amateur bands")


def grid_position(grid):
    grid = str(grid).upper()
    if not re.fullmatch(r"[A-R]{2}[0-9]{2}(?:[A-X]{2})?", grid):
        raise UdcError(f"GridSquare: invalid Maidenhead locator {grid}")
    lon = (ord(grid[0]) - 65) * 20 + int(grid[2]) * 2 - 180
    lat = (ord(grid[1]) - 65) * 10 + int(grid[3]) - 90
    if len(grid) == 6:
        lon += (ord(grid[4]) - 65) / 12 + 1 / 24
        lat += (ord(grid[5]) - 65) / 24 + 1 / 48
    else:
        lon += 1
        lat += 0.5
    return math.radians(lat), math.radians(lon)


def distance(a, b):
    lat1, lon1 = grid_position(a)
    lat2, lon2 = grid_position(b)
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return max(1, round(6371 * 2 * math.asin(min(1, math.sqrt(h)))))


def geography(data: bytes) -> dict:
    """Read not1mm JSON or an original CTY.DAT, including per-prefix overrides."""
    text = decode(data)
    if text.lstrip().startswith("{"):
        table = json.loads(text)
        return {k: v for k, v in table.items() if isinstance(v, dict)}
    text = re.sub(r"(?m)^#[\s\S]*?;", "", text)
    result = {}
    for block in text.split(";"):
        if not block.strip():
            continue
        parts = block.strip().split(":", 8)
        if len(parts) != 9:
            raise UdcError("Malformed CTY.DAT country record")
        name, cq, itu, cont, _lat, _lon, _tz, prefix, aliases = map(str.strip, parts)
        try:
            base = {
                "entity": name + (" (not DXCC)" if prefix.startswith("*") else ""),
                "cq": int(cq),
                "itu": int(itu),
                "continent": cont,
                "primary_pfx": prefix.lstrip("*").upper(),
                "exact_match": False,
            }
        except ValueError as exc:
            raise UdcError("Malformed CTY.DAT zone") from exc
        for alias in [prefix] + list(csv(aliases.replace("\n", "").replace("\r", ""))):
            item = base.copy()
            for pattern, key, convert in [
                (r"\((\d+)\)", "cq", int),
                (r"\[(\d+)\]", "itu", int),
                (r"\{([A-Z]+)\}", "continent", str),
            ]:
                match = re.search(pattern, alias)
                if match:
                    item[key] = convert(match[1])
            clean = (
                re.sub(r"\([^)]*\)|\[[^]]*\]|\{[^}]*\}|<[^>]*>|~[^~]*~", "", alias)
                .strip()
                .upper()
            )
            item["exact_match"] = clean.startswith("=")
            clean = clean.lstrip("=*")
            if clean:
                result[clean] = item
    if not result:
        raise UdcError("Empty geography database")
    return result


def lookup(table, call):
    call = call.upper()
    wae = None
    for end in range(len(call), 0, -1):
        entry = table.get(call[:end])
        if not entry or (entry.get("exact_match") and end != len(call)):
            continue
        if "(not DXCC)" in entry.get("entity", ""):
            wae = wae or entry
            continue
        # WAE subdivisions retain their own zones/continent, but score with their
        # parent DXCC unless UsesWAECountries is explicitly supported in future.
        return dict(wae, primary_pfx=entry["primary_pfx"]) if wae else entry
    return {}


def _valid_condition(token):
    upper = token.upper()
    known = {
        "MYCOUNTRY",
        "SAMECONTINENT",
        "OTHERCONTINENT",
        "MYCONTINENT",
        "ISCOMMENT",
        "ISMISC",
        "EXCHANGE",
        "MISC",
        "EXCH",
        "EXCHISNUM",
        "MISCISNUM",
        "EXCHISNOTNUM",
        "MYGRID",
        "MYCQZONE",
        "MYIARUZONE",
        "MYEXCHANGE",
        "ISMULT1",
        "ISMULT2",
        "ISMULT3",
    }
    return (
        upper in known | CONTINENTS | MODES
        or token.lower() in BANDS
        or re.fullmatch(
            r"(?:SAMECONTINENT|OTHERCONTINENT)\+(?:160|80|40|20|15|10)", upper
        )
        or re.fullmatch(r"(?:EXCHIS|MISCIS|SECTIS)_[A-Z0-9*]+", upper)
        or re.fullmatch(r"EXCHIS\*[A-Z0-9]+", upper)
        or re.fullmatch(r"/[A-Z]+", upper)
        or re.fullmatch(r"[A-Z0-9]{1,12}(?:/[A-Z0-9]+)?", upper)
    )


def validate_rules(d: Definition):
    for key in ("pointspercontact", "bonuspoints"):
        value = d.get(key, "1" if key == "pointspercontact" else "")
        if re.fullmatch(r"\d+", value):
            if key == "bonuspoints":
                raise UdcError("BonusPoints: expected condition, points pairs")
            continue
        if ";" in value and key == "pointspercontact":
            for entry in value.strip("; ").split(";"):
                if not re.fullmatch(r"\s*\d+/\d+/\d+\s*", entry):
                    raise UdcError(f"{key}: invalid distance table")
            continue
        for condition, amount in pairs(value, key):
            if not _valid_condition(condition) or not re.fullmatch(
                r"[+*]?\d+|\+?\*|\*\*", amount
            ):
                raise UdcError(
                    f"{key}: unsupported condition/value {condition}, {amount}"
                )
    for key in (
        "pointsmultbyband",
        "pointsmultbymode",
        "pointsmultbycontinent",
        "pointsmultbycountry",
        "pointsmultbycategory",
    ):
        for condition, value in pairs(d.get(key), key):
            if not re.fullmatch(r"\d+(?:\.\d+)?", value):
                raise UdcError(f"{key}: invalid factor {value}")
            if key.endswith("band"):
                if condition not in {str(x[2]) for x in BANDS.values()}:
                    raise UdcError(f"{key}: {condition}")
            elif (
                key.endswith("mode")
                and condition.upper() not in MODES
                or key.endswith("continent")
                and condition.upper()
                not in CONTINENTS | {"MYCONTINENT", "OTHERCONTINENT"}
                or key.endswith("category")
                and condition.upper() not in {"QRP", "QRPP"}
            ):
                raise UdcError(f"{key}: {condition}")
    value = d.get("pointsmultattimegmt", d.get("pointmultattimegmt"))
    if value:
        parts = csv(value)
        if len(parts) != 3 or not all(x.isdigit() for x in parts):
            raise UdcError("PointsMultAtTimeGMT: expected HHMM, HHMM, factor")
        if any(int(x) // 100 > 23 or int(x) % 100 > 59 for x in parts[:2]):
            raise UdcError("Invalid UTC multiplier time")
    if d.get("bonuspoints2") and not re.fullmatch(
        r"[+*]?\d+", csv(d.get("bonuspoints2"))[0]
    ):
        raise UdcError("BonusPoints2: unsupported points")
    workable = d.get("isworkable", "Any").upper()
    if workable not in {
        "ANY",
        "MYCONTINENTONLY",
        "NAONLY",
        "SAONLY",
        "EUONLY",
        "ASIAONLY",
        "AFONLY",
        "OCONLY",
        "MYCOUNTRYONLY",
        "EXCEPTMYCOUNTRY",
    } and not all(re.fullmatch(r"[A-Z0-9/]+", p) for p in csv(workable)):
        raise UdcError(f"IsWorkable={workable}: unsupported selector")


@dataclass(frozen=True)
class Result:
    contacts: tuple[dict, ...]
    points: int
    multipliers: tuple[int, int, int]
    score: int


class Engine:
    def __init__(
        self,
        definition,
        resources,
        station,
        settings,
        geo,
        engine_version=ENGINE_VERSION,
    ):
        self.d = definition
        self.version = engine_version
        self.resources = dict(resources)
        self.station = dict(station)
        self.settings = dict(settings)
        self.geo = geo
        self.mine = lookup(geo, self.station.get("Call", ""))
        self.validate_geographic_rules()
        self.sections = {}
        for name in definition.dependencies:
            match = next(
                (v for k, v in resources.items() if k.casefold() == name.casefold()),
                None,
            )
            if match is None:
                raise UdcError(f"Missing dependency: {name}")
            if name.lower().endswith(".sec"):
                lines = decode(match, definition.encoding).splitlines()
                if not lines or not lines[0].upper().startswith("TYPE="):
                    raise UdcError(f"{name}: expected Type= header")
                expected = name[:-4].upper()
                actual = lines[0].split()[0][5:].upper()
                if actual != expected:
                    raise UdcError(f"{name}: Type={actual} does not match filename")
                self.sections[expected] = (
                    parse_sections(lines[1:], name)
                    if self.version >= 2
                    else {
                        line.strip().upper().split(",")[0]: line.strip()
                        .upper()
                        .split(",")[0]
                        for line in lines[1:]
                        if line.strip() and not line.lstrip().startswith(";")
                    }
                )

    def validate_geographic_rules(self):
        countries = {str(v.get("primary_pfx", "")).upper() for v in self.geo.values()}
        known = {
            "MYCOUNTRY",
            "SAMECONTINENT",
            "OTHERCONTINENT",
            "MYCONTINENT",
            "ISCOMMENT",
            "ISMISC",
            "EXCHANGE",
            "MISC",
            "EXCH",
            "EXCHISNUM",
            "MISCISNUM",
            "EXCHISNOTNUM",
            "MYGRID",
            "MYCQZONE",
            "MYIARUZONE",
            "MYEXCHANGE",
            "ISMULT1",
            "ISMULT2",
            "ISMULT3",
        }
        for key in ("pointspercontact", "bonuspoints"):
            value = self.d.get(key)
            if not value or value.isdigit() or ";" in value:
                continue
            for token, amount in pairs(value, key):
                upper = token.upper()
                if (
                    upper not in known | CONTINENTS | MODES | countries
                    and token.lower() not in BANDS
                    and not re.fullmatch(
                        r"(?:SAMECONTINENT|OTHERCONTINENT)\+\d+|(?:EXCHIS|MISCIS|SECTIS)[_*][A-Z0-9*]+|/[A-Z]+|[A-Z0-9]*[0-9][A-Z0-9/]*",
                        upper,
                    )
                ):
                    raise UdcError(
                        f"{key}: unknown selector/country {token}; verify the selected CTY file"
                    )
                if "*" in amount and upper not in ("EXCHANGE", "MISC", "ISCOMMENT"):
                    raise UdcError(
                        f"{key}: numeric field points require Exchange, Misc or IsComment"
                    )
        for suffix in ("", "2", "3"):
            selector = self.d.get("multsqlstring" + suffix).upper()
            if self.d.flag("donotcountmeasmult" + suffix) and selector not in (
                "COUNTRYPREFIX",
                "SECTION",
                "GRID",
                "FIELD",
                "WPXPREFIX",
            ):
                raise UdcError(
                    f"DoNotCountMeAsMult{suffix}: unsupported selector {selector}"
                )

    def session(self, q):
        value = self.d.get("multiplesessions")
        if not value:
            return 0
        start, length = map(int, value.split("/"))
        minute = stamp(q["TS"])
        # Include the day so the same tour number on consecutive dates is distinct.
        return (
            minute.toordinal() * 1440
            + minute.hour * 60
            + minute.minute
            - (start // 100 * 60 + start % 100)
        ) // (length // 100 * 60 + length % 100)

    def normalize(self, contact):
        q = dict(contact)
        stamp(q.get("TS", ""))
        q["Call"] = str(q.get("Call", "")).strip().upper()
        if not re.fullmatch(r"[A-Z0-9/]+", q["Call"]) or not any(
            x.isdigit() for x in q["Call"]
        ):
            raise UdcError("Call: invalid callsign")
        name, q["Band"] = band(q.get("Freq"))
        if name in ("30m", "17m", "12m") and not self.d.flag("showwarcbands"):
            raise UdcError(f"{name}: WARC bands are disabled for this UDC")
        q["Mode"] = mode(q.get("Mode", ""))
        allowed = self.d.get("mode", "CW")
        if (
            allowed != "BOTH"
            and q["Mode"] != allowed
            and not (
                allowed == "RTTY"
                and self.d.flag("digitalmodesqlstring")
                and q["Mode"] == "PSK"
            )
        ):
            raise UdcError(f"Mode: {allowed} required, got {q['Mode']}")
        if q["Mode"] not in (MODES if self.version >= 3 else MODES - {"FT8", "FT4"}):
            raise UdcError(f"Unsupported mode: {q['Mode']}")
        for f in self.d.fields:
            q[f.column] = str(q.get(f.column, "")).strip().upper()
            if (
                f.column in ("SentNr", "NR")
                and q[f.column]
                and not q[f.column].isdigit()
            ):
                raise UdcError(f"{f.label}: expected serial number")
            if f.column == "GridSquare":
                grid_position(q[f.column])
            if any(ord(x) < 32 for x in q[f.column]):
                raise UdcError(f"{f.label}: control characters are not allowed")
        info = lookup(self.geo, q["Call"])
        if not info:
            raise UdcError(f"No geography entry for {q['Call']} in journal snapshot")
        q["CountryPrefix"] = info.get("primary_pfx", "").upper()
        q["Continent"] = info.get("continent", "")
        q["ZN"] = info.get("cq", 0)

        q["WPXPrefix"] = calculate_wpx_prefix(q["Call"])
        # Section and zone exchanges are stored separately while retaining original text.
        exchange = str(q.get("Exchange1", "")).upper()
        sec = self.sections.get(self.d.get("multwindowtype", "Section").upper(), {})
        section_input = (
            exchange
            if self.version == 1 or any(f.column == "Exchange1" for f in self.d.fields)
            else str(q.get("Sect", "")).upper()
        )
        q["Sect"] = (
            sec[section_input]
            if section_input in sec
            else (
                ""
                if any(f.column == "Exchange1" for f in self.d.fields)
                else str(q.get("Sect", "")).upper()
            )
        )
        if (
            exchange.isdigit()
            and 1 <= int(exchange) <= 40
            and any(
                self.d.get("multsqlstring" + s).upper() == "CQZONE"
                for s in ("", "2", "3")
            )
        ):
            q["ZN"] = int(exchange)
        for rule in csv(self.d.get("qsoerrorstring")):
            target = None
            for token, column in FIELDS.items():
                if rule.lower().startswith(token + "_"):
                    target = column
                    rule = rule[len(token) + 1 :]
                    break
            rule = rule.lower()
            targets = (
                [target]
                if target
                else [
                    f.column
                    for f in self.d.fields
                    if f.column in ("Exchange1", "MiscText", "Comment", "Name")
                ]
            )
            if rule == "grid":
                targets = ["GridSquare"]
            if rule not in (
                "grid",
                "any",
                "any_or_empty",
                "any_not_empty",
                "numeric",
                "numeric_not_empty",
            ):
                targets = [target or "Exchange1"]
            for col in targets:
                value = str(q.get(col, ""))
                if rule == "grid":
                    grid_position(value)
                elif rule.startswith(("any", "numeric")):
                    if rule.endswith("_not_empty") and not value:
                        raise UdcError(f"{col}: value is required")
                    if len(value) > 12 or (
                        rule.startswith("numeric") and value and not value.isdigit()
                    ):
                        raise UdcError(f"{col}: failed {rule}")
                else:
                    key = rule.removesuffix("_or_empty").upper()
                    if value not in self.sections.get(key, set()) and not (
                        not value and rule.endswith("_or_empty")
                    ):
                        raise UdcError(f"{col}: unknown section {value} ({key})")
        for col in ("SNT", "RCV"):
            if col not in {f.column for f in self.d.fields}:
                q[col] = ""
        return q

    def dupe_key(self, q):
        if self.version >= 3 and self.d.repeat.minutes and self.d.repeat.extended:
            parts = [q["Call"], self.session(q)]
            if not self.d.repeat.ignore_band:
                parts.append(q["Band"])
            if self.d.repeat.this_mode:
                parts.append(self.mode_key(q))
            return tuple(parts)
        parts = [q["Call"], self.session(q)]
        kind = self.d.integer("dupetype", 2)
        if kind == 4:
            if self.version < 3 or not self.d.repeat.minutes:
                return None
            parts.append(q["Band"])
        if kind in (2, 3):
            parts.append(q["Band"])
        if kind == 3:
            parts.append(self.mode_key(q))
        extra = self.d.integer("dupesqlstring")
        if extra:
            parts.append(
                q.get(
                    {1: "Sect", 2: "Exchange1", 3: "Mode", 4: "GridSquare"}[extra], ""
                )
            )
        return tuple(parts)

    def mode_key(self, q):
        return (
            "DIGI"
            if self.d.flag("digitalmodesqlstring") and q["Mode"] in ("RTTY", "PSK")
            else q["Mode"]
        )

    def condition(self, token, q, flags=()):
        t = token.upper()
        country = q["CountryPrefix"]
        cont = q["Continent"]
        mycountry = str(self.mine.get("primary_pfx", "")).upper()
        mycont = self.mine.get("continent", "")
        ex = str(q.get("Exchange1", ""))
        misc = str(q.get("MiscText", ""))
        same = cont == mycont
        basics = {
            "MYCOUNTRY": country == mycountry,
            "SAMECONTINENT": same,
            "MYCONTINENT": same,
            "OTHERCONTINENT": not same,
            "ISCOMMENT": bool(q.get("Comment")),
            "ISMISC": bool(misc),
            "EXCH": bool(ex),
            "EXCHISNUM": ex.isdigit(),
            "MISCISNUM": misc.isdigit(),
            "EXCHISNOTNUM": bool(ex) and not ex.isdigit(),
            "EXCHANGE": ex.isdigit(),
            "MISC": misc.isdigit(),
            "MYEXCHANGE": ex == self.settings.get("SentExchange", ""),
            "MYCQZONE": str(q["ZN"])
            == str(self.station.get("CQZone", self.mine.get("cq", ""))),
            "MYIARUZONE": str(lookup(self.geo, q["Call"]).get("itu", ""))
            == str(self.station.get("IARUZone", self.mine.get("itu", ""))),
            "MYGRID": q.get("GridSquare", "")[:4]
            == self.station.get("GridSquare", "")[:4],
        }
        if t in basics:
            return basics[t]
        if t in ("ISMULT1", "ISMULT2", "ISMULT3"):
            return bool(flags and flags[int(t[-1]) - 1])
        if t in CONTINENTS:
            return cont == t
        if t == "DIGI" and self.version >= 3:
            return q["Mode"] in DIGITAL_MODES
        if t in MODES:
            return mode(t) == q["Mode"]
        if token.lower() in BANDS:
            return q["Band"] == BANDS[token.lower()][2]
        if "+" in t:
            base, meters = t.split("+", 1)
            return self.condition(base, q, flags) and band(q["Freq"])[0] == meters + "m"
        if t.startswith(("EXCHIS_", "MISCIS_", "SECTIS_")):
            selector, value = t.split("_", 1)
            source = {"EXCHIS": ex, "MISCIS": misc, "SECTIS": str(q.get("Sect", ""))}[
                selector
            ]
            return source == ("" if value == "EMPTY" else value)
        if t.startswith("EXCHIS*"):
            return t[7:] in ex
        if t.startswith("/"):
            return q["Call"].endswith(t)
        return country == t or q["Call"] == t

    def amount(self, base, value, q, token):
        operator = value[0] if value[0] in "+*" else ""
        number = value[1:] if operator else value
        if number == "*" or value == "*":
            col = {
                "EXCHANGE": "Exchange1",
                "MISC": "MiscText",
                "ISCOMMENT": "Comment",
            }.get(token.upper())
            if col is None:
                raise UdcError(
                    f"Numeric points require Exchange, Misc or IsComment, got {token}"
                )
            match = re.search(r"\d+", str(q.get(col, "")))
            n = int(match[0]) if match else 0
            if value == "*":
                operator = ""
        else:
            n = int(number)
        return base + n if operator == "+" else base * n if operator == "*" else n

    def points(self, q, flags):
        rule = self.d.get("pointspercontact", "1")
        if rule.isdigit():
            points = int(rule)
            if self.d.get("name").upper().startswith("VHF"):
                points *= distance(
                    self.station.get("GridSquare", ""), q.get("GridSquare", "")
                )
        elif ";" in rule:
            km = distance(self.station.get("GridSquare", ""), q.get("GridSquare", ""))
            points = 0
            for entry in rule.strip("; ").split(";"):
                low, high, value = map(int, entry.split("/"))
                if low <= km <= high:
                    points = value
                    break
        else:
            points = 1
            matching = [
                (token, value)
                for token, value in pairs(rule, "PointsPerContact")
                if self.condition(token, q, flags)
            ]

            # Specific selectors precede geographic fallbacks. Among specific band/mode
            # rules the documented band > mode order applies; declaration order breaks ties.
            def priority(item):
                token = item[0].upper()
                if token == "MYEXCHANGE" or token.startswith(
                    ("SECTIS_", "EXCHIS_", "MISCIS_")
                ):
                    return -1
                if token.lower() in BANDS or "+" in token:
                    return 0
                if token in MODES:
                    return 1
                if token in ("SAMECONTINENT", "OTHERCONTINENT", "MYCOUNTRY"):
                    return 4
                return 2

            if matching:
                token, value = min(matching, key=priority)
                points = self.amount(points, value, q, token)
        for key in (
            "pointsmultbyband",
            "pointsmultbymode",
            "pointsmultbycontinent",
            "pointsmultbycountry",
            "pointsmultbycategory",
        ):
            for token, value in pairs(self.d.get(key), key):
                yes = (
                    (float(token) == q["Band"])
                    if key.endswith("band")
                    else self.condition(
                        "/" + token if key.endswith("category") else token, q, flags
                    )
                )
                if yes:
                    points *= float(value)
                    break
        time_rule = self.d.get("pointsmultattimegmt", self.d.get("pointmultattimegmt"))
        if time_rule:
            low, high, factor = map(int, csv(time_rule))
            time = stamp(q["TS"])
            now = time.hour * 100 + time.minute
            if low <= now <= high if low <= high else now >= low or now <= high:
                points *= factor
        bonus = [
            (t, v)
            for t, v in pairs(self.d.get("bonuspoints"), "BonusPoints")
            if self.condition(t, q, flags)
        ]
        if bonus:
            token, value = bonus[0]
            points = self.amount(points, value, q, token)
        if self.d.get("bonuspoints2"):
            value, name = csv(self.d.get("bonuspoints2"))
            contents = next(
                data
                for key, data in self.resources.items()
                if key.casefold() == name.casefold()
            )
            text = decode(contents, self.d.encoding).upper()
            entries = csv(text.replace("\n", ","))
            if (
                entries
                and re.fullmatch(r"[A-R]{2}\d{2}", entries[0])
                and len(entries) % 2 == 0
            ):
                grid_points = dict(zip(entries[::2], entries[1::2]))
                if q.get("GridSquare", "")[:4] in grid_points:
                    points = self.amount(
                        points,
                        ("+" if value.startswith("+") else "")
                        + str(
                            int(value.lstrip("+"))
                            * int(grid_points[q["GridSquare"][:4]])
                        ),
                        q,
                        "",
                    )
            elif q["Call"] in entries:
                points = self.amount(points, value, q, "")
        return int(points)

    def multiplier_bands(self):
        hf = {"160m", "80m", "40m", "20m", "15m", "10m"}
        return {
            1: hf,
            2: hf | {"30m", "17m", "12m"},
            3: hf | {"6m", "2m"},
            4: set(BANDS) - hf - {"30m", "17m", "12m"},
        }[self.d.integer("multiplierbands", 1)]

    def off_times(self, contacts, start=None, end=None):
        from .operating import off_times, schedule_window

        if start is None or end is None:
            default_start, default_end = schedule_window(
                self.d, self.settings.get("StartDate")
            )
            start, end = start or default_start, end or default_end
        if start is None or end is None:
            raise UdcError(
                "OFF times need an explicit start and end; this UDC has missing or identical calendar endpoints"
            )
        return off_times(contacts, start, end, self.d.integer("minimumofftime", 30))

    def mult_key(self, q, index):
        if self.version >= 2 and band(q["Freq"])[0] not in self.multiplier_bands():
            return None
        suffix = "" if index == 1 else str(index)
        selector = self.d.get("multsqlstring" + suffix, "N/A").upper()
        scope = self.d.integer(
            "ismult" + str(index) + "per", self.d.integer("ismultper")
        )
        if scope == 0 or selector == "N/A":
            return None
        for key, negative in [
            ("countmultonlyfor", False),
            ("donotcountmultonlyfor", True),
        ]:
            allowed = csv(self.d.get(key + suffix).upper())
            match = any(
                q["CountryPrefix"] == x
                or q["CountryPrefix"].startswith(x + "/")
                or q["Continent"] == x
                for x in allowed
            )
            if allowed and match == negative:
                return None
        sections = csv(self.d.get("countmultonlyforsec" + suffix).upper())
        if sections and q.get("Sect") not in sections:
            return None
        grid = str(q.get("GridSquare", ""))
        values = {
            "COUNTRYPREFIX": q["CountryPrefix"],
            "SECTION": q.get("Sect", ""),
            "WPXPREFIX": q.get("WPXPrefix", ""),
            "GRID": grid[:4],
            "SGRID": grid[:6],
            "FIELD": grid[:2],
            "CALLSIGN": q["Call"],
            "FIRSTQSO": "first",
            "MISC": q.get("MiscText", ""),
            "EXCHANGE": q.get("Exchange1", ""),
            "CQZONE": str(q["ZN"]),
            "IARUZONE": q.get("MiscText", ""),
            "2LPREFIX": q["Call"][:2],
            "LASTLETTER": q["Call"].rstrip("0123456789")[-1:],
        }
        if selector.endswith("_COUNTRY"):
            if q["Continent"] != selector.split("_")[0]:
                return None
            value = q["CountryPrefix"]
        else:
            value = values.get(selector, "")
        if not value:
            return None
        if self.d.flag("donotcountmeasmult" + suffix):
            own_section = self.settings.get("SentExchange", "")
            if self.version >= 2 and selector == "SECTION":
                sections = self.sections.get(
                    self.d.get("multwindowtype", "Section").upper(), {}
                )
                own_section = next(
                    (
                        sections[x]
                        for x in reversed(own_section.upper().split())
                        if x in sections
                    ),
                    own_section,
                )
            own = {
                "COUNTRYPREFIX": str(self.mine.get("primary_pfx", "")).upper(),
                "SECTION": own_section,
                "GRID": self.station.get("GridSquare", "")[:4],
                "FIELD": self.station.get("GridSquare", "")[:2],
                "WPXPREFIX": calculate_wpx_prefix(self.station.get("Call", "")),
            }.get(selector)
            if own is None:
                raise UdcError(f"DoNotCountMeAsMult: unsupported selector {selector}")
            if value == own:
                return None
        key = [value]
        if scope in (1, 3):
            key.append(q["Band"])
        if scope in (2, 3):
            key.append(self.mode_key(q))
        if self.d.flag("resetmultseverysession"):
            key.append(self.session(q))
        return tuple(key)

    def workable(self, q):
        value = self.d.get("isworkable", "Any").upper()
        if value == "ANY":
            return True
        mapping = {
            "MYCONTINENTONLY": "SAMECONTINENT",
            "MYCOUNTRYONLY": "MYCOUNTRY",
            "NAONLY": "NA",
            "SAONLY": "SA",
            "EUONLY": "EU",
            "ASIAONLY": "AS",
            "AFONLY": "AF",
            "OCONLY": "OC",
        }
        if value == "EXCEPTMYCOUNTRY":
            return not self.condition("MYCOUNTRY", q)
        return any(self.condition(mapping.get(v, v), q) for v in csv(value))

    def duplicate_time(self, ts):
        time = stamp(ts)
        if (
            self.version >= 3
            and self.d.repeat.extended
            and not self.d.repeat.compare_seconds
        ):
            time = time.replace(second=0)
        return time

    def duplicate_decision(self, proposed, index):
        """The only interval/boundary decision used by score, entry and bandmap."""
        key = self.dupe_key(proposed)
        elapsed = (
            (self.duplicate_time(proposed["TS"]) - index[key]).total_seconds()
            if key in index
            else None
        )
        limit = self.d.repeat.minutes * 60
        dupe = (
            key is not None and elapsed is not None and (not limit or elapsed < limit)
        )
        return {
            "isdupe": int(dupe),
            "elapsed_minutes": None if elapsed is None else elapsed / 60,
            "wait_seconds": max(0, limit - elapsed)
            if elapsed is not None and dupe
            else 0,
        }

    def duplicate_sequence(self, contacts):
        """Scalar rules anchor to credited QSOs; five-part rules to recorded QSOs."""
        seen = {}
        for original in sorted(contacts, key=lambda q: (q["TS"], q.get("ID", ""))):
            q = self.normalize(original)
            status = self.duplicate_decision(q, seen)
            dupe = bool(status["isdupe"])
            key = self.dupe_key(q)
            if key is not None and (
                not dupe or self.version >= 3 and self.d.repeat.extended
            ):
                seen[key] = self.duplicate_time(q["TS"])
            yield q, dupe, status["elapsed_minutes"]

    def duplicate_index(self, contacts, now, exclude_id=None):
        """Reconstruct a validated history, excluding future rows and edited ID."""
        seen = {}
        cutoff = stamp(now)
        for q, dupe, _ in self.duplicate_sequence(
            r
            for r in contacts
            if stamp(r["TS"]) <= cutoff
            and (exclude_id is None or r.get("ID") != exclude_id)
        ):
            key = self.dupe_key(q)
            if key is not None and (
                not dupe or self.version >= 3 and self.d.repeat.extended
            ):
                seen[key] = self.duplicate_time(q["TS"])
        return seen

    def duplicate_status(self, contacts, proposed, index=None):
        # A proposed entry may be incomplete. Bandmap reuses the validated index.
        if index is None:
            index = self.duplicate_index(contacts, proposed["TS"], proposed.get("ID"))
        return self.duplicate_decision(proposed, index)

    def band_status(self, contacts, now, radio=1):
        from .band_changes import band_status

        return band_status(self, contacts, now, radio)

    def evaluate(self, contacts):
        mults = [set(), set(), set()]
        out = []
        for q, dupe, _ in self.duplicate_sequence(contacts):
            flags = [0, 0, 0]
            if not dupe and self.workable(q):
                for i in range(self.d.integer("nummults", 1)):
                    m = self.mult_key(q, i + 1)
                    if m is not None and m not in mults[i]:
                        flags[i] = 1
                        mults[i].add(m)
                points = self.points(q, flags)
            else:
                points = 0
            q.update(
                Points=points,
                IsMultiplier1=flags[0],
                IsMultiplier2=flags[1],
                isMultiplier3=flags[2],
            )
            q["_dupe"] = dupe
            out.append(q)
        points = sum(q["Points"] for q in out)
        counts = tuple(len(m) for m in mults)
        scored = [
            i
            for i in range(self.d.integer("nummults", 1))
            if self.d.get("multmult" + ("" if i == 0 else str(i + 1)), "1").lower()
            not in ("0", "false", "no")
            and self.d.integer(
                "ismult" + str(i + 1) + "per", self.d.integer("ismultper")
            )
        ]
        factor = sum(counts[i] for i in scored) if scored else 1
        return Result(tuple(out), points, counts, points * factor)

    def next_serial(self, contacts, now, frequency):
        q = {"TS": now}
        items = list(contacts)
        if self.d.flag("resetsneverysession"):
            items = [r for r in items if self.session(r) == self.session(q)]
        byband = self.d.integer("qsonumbersbyband")
        if byband == 1 or (
            byband == 2 and self.settings.get("TransmitterCategory") == "UNLIMITED"
        ):
            target = band(frequency)[1]
            items = [r for r in items if band(r["Freq"])[1] == target]
        return max((int(r.get("SentNr", 0) or 0) for r in items), default=0) + 1
