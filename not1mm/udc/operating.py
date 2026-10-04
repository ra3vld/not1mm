"""UTC calendar hints and full-clock-minute operating/OFF time calculations.

Calendar hints affect this report only, never QSO validity or scoring. Ambiguous
identical start/end hints require explicit dates instead of inventing a duration.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .model import UdcError


def as_time(value):
    if isinstance(value, datetime):
        if value.tzinfo is not None and value.utcoffset() != timedelta(0):
            raise UdcError("OFF times must use UTC")
        return value.replace(tzinfo=UTC)
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError as exc:
        raise UdcError("OFF times require UTC YYYY-MM-DD HH:MM:SS") from exc


def schedule_window(definition, anchor):
    if not anchor or definition.start is None:
        return None, None
    day = as_time(anchor).replace(hour=0, minute=0, second=0, microsecond=0)
    start = (
        day
        - timedelta(days=(day.weekday() - definition.start.weekday) % 7)
        + timedelta(minutes=definition.start.minutes)
    )
    if definition.end is None:
        return start, None
    duration = (
        (definition.end.weekday - definition.start.weekday) * 1440
        + definition.end.minutes
        - definition.start.minutes
    ) % (7 * 1440)
    return start, start + timedelta(minutes=duration) if duration else None


@dataclass(frozen=True)
class OffTimes:
    start: datetime
    end: datetime
    intervals: tuple[tuple[datetime, datetime], ...]
    on_minutes: int
    off_minutes: int
    outside_qsos: int

    def text(self):
        lines = [
            f"UTC: {self.start:%Y-%m-%d %H:%M} – {self.end:%Y-%m-%d %H:%M}",
            f"Operating: {self.on_minutes} min; OFF: {self.off_minutes} min",
            f"QSOs outside report interval: {self.outside_qsos}",
        ]
        lines += [
            f"OFF: {a:%Y-%m-%d %H:%M} – {b:%Y-%m-%d %H:%M} ({int((b - a).total_seconds() // 60)} min)"
            for a, b in self.intervals
        ]
        return "\n".join(lines)


def off_times(contacts, start, end, minimum=30):
    start, end = as_time(start), as_time(end)
    if end <= start:
        raise UdcError("OFF report end must be after start")
    if not isinstance(minimum, int) or not 0 <= minimum <= 10080:
        raise UdcError("MinimumOffTime must be 0..10080 minutes")
    # Count only complete clock minutes; a minute with any QSO is operating time.
    left = start.replace(second=0, microsecond=0)
    if left < start:
        left += timedelta(minutes=1)
    right = end.replace(second=0, microsecond=0)
    right = max(right, left)
    stamps = [as_time(q["TS"]) for q in contacts]
    minutes = sorted(
        {t.replace(second=0, microsecond=0) for t in stamps if left <= t < right}
    )
    intervals = []
    cursor = left
    for i, minute in enumerate(minutes):
        gap = int((minute - cursor).total_seconds() // 60)
        if gap > 0 and (i == 0 or gap >= minimum):
            intervals.append((cursor, minute))
        cursor = minute + timedelta(minutes=1)
    if cursor < right:
        intervals.append((cursor, right))
    total = max(0, int((right - left).total_seconds() // 60))
    off = sum(int((b - a).total_seconds() // 60) for a, b in intervals)
    return OffTimes(
        start,
        end,
        tuple(intervals),
        total - off,
        off,
        sum(not start <= t < end for t in stamps),
    )
