"""Reconstruct per-radio band counters and hold timers from journal contacts.

These are operating warnings, not scoring disqualifications. No live CAT event
is persisted: the first logged contact on a different band initiates a change.
"""

import math
from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class BandStatus:
    count: int = 0
    maximum: int = 0
    counter_enabled: bool = False
    timer_minutes: int = 0
    remaining_seconds: int = 0
    warnings: tuple[tuple[str, str], ...] = ()

    @property
    def severity(self):
        if self.counter_enabled and self.count >= self.maximum:
            return "red"
        if self.counter_enabled and self.count == self.maximum - 1:
            return "yellow"
        return "normal"

    def text(self):
        parts = []
        if self.counter_enabled:
            parts.append(f"Band/mode changes: {self.count}/{self.maximum}")
        if self.timer_minutes:
            parts.append(
                f"Stay on band: {self.remaining_seconds // 60:02}:{self.remaining_seconds % 60:02}"
            )
        return " | ".join(parts)


def band_status(engine, contacts, now, radio=1):
    from .engine import band, mode, stamp

    if engine.version < 3:
        return BandStatus()
    d = engine.d
    multi = engine.settings.get("OperatorCategory") == "MULTI-OP"
    prefix = "mo" if multi else "so"
    modern = any(
        d.flag(k)
        for k in (
            "singleopcountablebandchange",
            "multiopcountablebandchange",
            "countbandchangespercontest",
            "countbandchangesperperiod",
            "countbandormodechange",
        )
    ) or any(
        d.integer(k)
        for k in (
            "sobandchangecountmax",
            "mobandchangecountmax",
            "sobandchangetimerduration",
            "mobandchangetimerduration",
        )
    )
    legacy = d.get("bandchangesperperiod") if not modern else ""
    maximum = d.integer(prefix + "bandchangecountmax") or int(legacy or 0)
    enabled = bool(maximum) and (
        bool(legacy)
        or d.flag(
            "multiopcountablebandchange" if multi else "singleopcountablebandchange"
        )
    )
    timer = d.integer(prefix + "bandchangetimerduration")
    if not enabled and not timer:
        return BandStatus()
    now = stamp(now)

    def bucket(time):
        if d.flag("countbandchangespercontest"):
            return 0
        if d.flag("countbandchangesperperiod") or legacy:
            return engine.session({"TS": time.strftime("%Y-%m-%d %H:%M:%S")})
        return time.replace(minute=0, second=0)

    previous = {}
    counters = {}
    deadlines = {}
    warnings = []
    for q in sorted(contacts, key=lambda q: (q["TS"], q.get("ID", ""))):
        time = stamp(q["TS"])
        if time > now:
            continue
        stream = int(q.get("RadioNR") or 1)
        identity = (band(q["Freq"])[1], mode(q["Mode"]))
        prev = previous.get(stream)
        band_changed = prev is not None and identity[0] != prev[0]
        changed = (
            band_changed
            or prev is not None
            and d.flag("countbandormodechange")
            and identity[1] != prev[1]
        )
        key = (stream, bucket(time))
        if changed:
            counters[key] = counters.get(key, 0) + 1
            if stream == int(radio) and enabled and counters[key] > maximum:
                warnings.append(
                    (
                        q.get("ID", ""),
                        f"Band/mode change limit exceeded: {counters[key]}/{maximum}",
                    )
                )
        if prev is None or band_changed:
            deadline = deadlines.get(stream)
            if (
                stream == int(radio)
                and timer
                and deadline is not None
                and time < deadline
            ):
                warnings.append(
                    (q.get("ID", ""), "Band changed before hold timer expired")
                )
            deadlines[stream] = time + timedelta(minutes=timer)
        previous[stream] = identity
    deadline = deadlines.get(int(radio), now)
    return BandStatus(
        counters.get((int(radio), bucket(now)), 0),
        maximum,
        enabled,
        timer,
        max(0, math.ceil((deadline - now).total_seconds())),
        tuple(warnings),
    )
