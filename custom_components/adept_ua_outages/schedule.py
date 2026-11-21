"""Normalize data sources to exact intervals and renderable half-hour cells."""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from .const import KYIV
from .ua_outages.models import DaySchedule, Outage, merge_outages

ONE_DAY = timedelta(days=1)
HALF_HOUR = timedelta(minutes=30)
HOURS = tuple(str(hour) for hour in range(1, 25))
SLOT_STATES = {
    "yes": "00",
    "no": "11",
    "first": "10",
    "second": "01",
    "maybe": "22",
    "mfirst": "20",
    "msecond": "02",
}
GROUP_PATTERN = re.compile(r"[0-9]{1,3}(?:\.[0-9]{1,2})?")


@dataclass(frozen=True)
class PublishedSchedules:
    days: dict[date, DaySchedule]
    source: str | None = None


def merge_intervals(intervals: Iterable[Outage]) -> tuple[Outage, ...]:
    """Compare aware times in UTC, including across Kyiv clock changes."""
    return merge_outages(
        Outage(
            interval.start.astimezone(UTC),
            interval.end.astimezone(UTC),
            interval.possible,
        )
        for interval in intervals
        if interval.end.astimezone(UTC) > interval.start.astimezone(UTC)
    )


def _slots_to_intervals(day: date, slots: str) -> tuple[Outage, ...]:
    start = datetime.combine(day, time.min, KYIV).astimezone(UTC)
    end = datetime.combine(day + ONE_DAY, time.min, KYIV).astimezone(UTC)
    outages = []
    while start < end:
        local = start.astimezone(KYIV)
        state = slots[local.hour * 2 + local.minute // 30]
        following = start + HALF_HOUR
        if state != "0":
            outages.append(Outage(start, following, state == "2"))
        start = following
    return merge_intervals(outages)


def parse_community_schedule(payload: object, today: date) -> dict[date, DaySchedule]:
    """Decode a complete public GPV row while leaving invalid hours unpublished."""
    if not isinstance(payload, dict):
        raise TypeError("Invalid community feed")
    fact = payload.get("fact")
    if not isinstance(fact, dict) or not isinstance(fact.get("data"), dict):
        raise TypeError("Missing fact.data in the community feed")

    days: dict[date, DaySchedule] = {}
    for stamp, groups in fact["data"].items():
        if (
            not isinstance(stamp, str)
            or not stamp.isascii()
            or not stamp.isdecimal()
            or len(stamp) > 11
        ):
            continue
        day = datetime.fromtimestamp(int(stamp), KYIV).date()
        if day not in (today, today + ONE_DAY) or not isinstance(groups, dict):
            continue
        parsed = {}
        for key, row in groups.items():
            if not isinstance(key, str) or not isinstance(row, dict):
                continue
            queue = key.removeprefix("GPV")
            if not GROUP_PATTERN.fullmatch(queue):
                continue
            slots = [
                SLOT_STATES.get(row.get(hour, ""), "")
                if isinstance(row.get(hour), str)
                else ""
                for hour in HOURS
            ]
            if all(slots):
                parsed[queue] = _slots_to_intervals(day, "".join(slots))
        if parsed:
            days[day] = DaySchedule(day, groups=parsed)
    return days


def render_slots(day: date, intervals: tuple[Outage, ...]) -> str:
    """Use amber for possible outages and hatch only the partial confirmed cells."""
    midnight = datetime.combine(day, time.min)
    tomorrow = midnight + ONE_DAY
    periods = []
    for interval in intervals:
        start = interval.start.astimezone(KYIV).replace(tzinfo=None)
        end = interval.end.astimezone(KYIV).replace(tzinfo=None)
        periods.append((start, end, interval.possible))
    cells = []
    while midnight < tomorrow:
        end = midnight + HALF_HOUR
        overlapping = [
            (a, b, possible) for a, b, possible in periods if a < end and midnight < b
        ]
        if any(
            a <= midnight and end <= b and not possible
            for a, b, possible in overlapping
        ):
            cells.append("1")
        elif any(not possible for _, _, possible in overlapping):
            cells.append("3")
        else:
            cells.append("2" if overlapping else "0")
        midnight = end
    return "".join(cells)
