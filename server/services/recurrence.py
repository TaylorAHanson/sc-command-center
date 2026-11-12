"""When a schedule runs next: a recurrence, as people describe one, turned into instants.

A recurrence is `{freq, days, time, tz}` (the `/api/schedules` contract):

  * `hourly` runs every hour at the minute of `time`; its hour is ignored.
  * `daily` runs every day at `time`.
  * `weekly` runs on `days`, ISO weekdays from 1 (Monday) to 7 (Sunday).
  * `monthly` runs on `days` of the month, 1 to 31. A day past the month's end
    means its last day, so 31 is the 30th in April and the 28th or 29th in
    February, and 30 and 31 together still run once there.
  * `tz` is an IANA name. Times are wall-clock times in that zone, which is what
    "every Monday at 9" means to the person who set it.

Daylight saving moves the wall clock, so two local times need a rule:

  * one that doesn't exist (spring forward: 02:30 on the night clocks jump from
    02:00 to 03:00) runs at the first instant after it that does, 03:00;
  * one that happens twice (fall back: 01:30 when 02:00 becomes 01:00 again) runs
    once, at its first occurrence.

`hourly` is the exception: it runs every real hour, at whichever instant the local
clock shows that minute, so a night with a jump or a repeat has one hour fewer or
one more, rather than two runs half an hour apart.

No cron, and no dependency: `zoneinfo` reads the operating system's time zone
database, or the `tzdata` package where the system has none. Without either, only
UTC is available, and `validate` says so instead of storing a zone nothing can
read.
"""

from __future__ import annotations

import re
import zoneinfo
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any, Dict, List, Optional, Tuple

FREQS = ("hourly", "daily", "weekly", "monthly")
DEFAULT_TZ = "UTC"

_TIME = re.compile(r"^(\d{1,2}):(\d{2})$")
# What IANA names are made of. Narrower than what zoneinfo would try to open, which
# includes any file under the database's directory.
_TZ_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_+-]*(?:/[A-Za-z0-9_+-]+){0,2}$")
_UTC_NAMES = ("UTC", "Etc/UTC", "Etc/UCT", "UCT", "Zulu", "Etc/Zulu", "GMT", "Etc/GMT")
# Far enough ahead to reach any monthly day (a month whose last day is the 28th is
# followed by one with 31) with room to spare; a valid recurrence never gets close.
_SEARCH_DAYS = 400


def _zone(name: str) -> tzinfo:
    """The zone `name` names. UTC needs no database, so it works on a host without one."""
    try:
        return zoneinfo.ZoneInfo(name)
    except zoneinfo.ZoneInfoNotFoundError:
        if name in _UTC_NAMES:
            return timezone.utc
        raise


def _parse_time(value: Any) -> Optional[Tuple[int, int]]:
    match = _TIME.match(str(value or "").strip())
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def _days(value: Any, low: int, high: int) -> Optional[List[int]]:
    if not isinstance(value, (list, tuple)):
        return None
    out = set()
    for item in value:
        # A bool is an int to Python; true is not Monday.
        if isinstance(item, bool) or not isinstance(item, int) or not low <= item <= high:
            return None
        out.add(item)
    return sorted(out)


def validate(recurrence: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(normalized recurrence, None), or (None, a sentence saying what's wrong).

    Normalized means `freq` lowercased, `days` sorted and unique (empty for hourly
    and daily, which ignore them), `time` as zero-padded HH:MM, and `tz` a zone
    this host can read, UTC when none was given.
    """
    if not isinstance(recurrence, dict):
        return None, "Say how often it runs: hourly, daily, weekly or monthly."
    freq = str(recurrence.get("freq") or "").strip().lower()
    if freq not in FREQS:
        return None, "How often it runs must be hourly, daily, weekly or monthly."
    parsed = _parse_time(recurrence.get("time"))
    if parsed is None:
        return None, "The time must be HH:MM on a 24-hour clock, such as 09:00."
    hour, minute = parsed

    days: List[int] = []
    if freq == "weekly":
        found = _days(recurrence.get("days"), 1, 7)
        if not found:
            return None, "Pick at least one weekday, from 1 (Monday) to 7 (Sunday)."
        days = found
    elif freq == "monthly":
        found = _days(recurrence.get("days"), 1, 31)
        if not found:
            return None, "Pick at least one day of the month, from 1 to 31."
        days = found

    tz_name = str(recurrence.get("tz") or "").strip() or DEFAULT_TZ
    try:
        if len(tz_name) > 64 or not _TZ_NAME.match(tz_name):
            raise ValueError(tz_name)
        _zone(tz_name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError):
        if not zoneinfo.available_timezones():
            return None, ("This server has no time zone database, so schedules can only use UTC "
                          "until an administrator adds one.")
        return None, f"'{tz_name[:64]}' isn't a time zone this app knows, such as Europe/London."
    return {"freq": freq, "days": days, "time": f"{hour:02d}:{minute:02d}", "tz": tz_name}, None


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def resolve_local(day: date, at: time, tz: tzinfo) -> datetime:
    """The UTC instant the wall clock in `tz` shows `at` on `day`.

    A time that happens twice is its first occurrence (fold 0). A time that never
    happens is the first instant after it that does: the end of the jump, found
    between the two readings `zoneinfo` gives a missing time, one with the offset
    before the jump and one with the offset after.
    """
    naive = datetime.combine(day, at)
    first = naive.replace(tzinfo=tz, fold=0).astimezone(timezone.utc)
    if first.astimezone(tz).replace(tzinfo=None) == naive:
        return first
    other = naive.replace(tzinfo=tz, fold=1).astimezone(timezone.utc)
    lo, hi = min(first, other), max(first, other)
    before = lo.astimezone(tz).utcoffset()
    # Transitions fall on whole seconds, so this converges in a dozen or so steps.
    while hi - lo > timedelta(seconds=1):
        mid = lo + (hi - lo) / 2
        if mid.astimezone(tz).utcoffset() == before:
            lo = mid
        else:
            hi = mid
    return hi.replace(microsecond=0)


def _month_days(day: date, wanted: List[int]) -> set:
    if day.month == 12:
        last = 31
    else:
        last = (date(day.year, day.month + 1, 1) - timedelta(days=1)).day
    return {min(d, last) for d in wanted}


def _matches(freq: str, days: List[int], day: date) -> bool:
    if freq == "daily":
        return True
    if freq == "weekly":
        return day.isoweekday() in days
    return day.day in _month_days(day, days)


def _next_hourly(minute: int, tz: tzinfo, after: datetime) -> datetime:
    # Every real hour holds one instant whose local reading has this minute, except
    # an hour a half-hour shift cuts through, which the check below skips.
    start = after.replace(minute=0, second=0, microsecond=0)
    for step in range(0, 50):
        hour_start = start + timedelta(hours=step)
        offset = hour_start.astimezone(tz).utcoffset() or timedelta(0)
        local_minute = int(offset.total_seconds() // 60) % 60
        candidate = hour_start + timedelta(minutes=(minute - local_minute) % 60)
        if candidate > after and candidate.astimezone(tz).minute == minute:
            return candidate
    raise ValueError("no hourly run found within two days")


def next_run(recurrence: Dict[str, Any], after_utc: datetime) -> datetime:
    """The first instant strictly after `after_utc` that the recurrence names, as aware UTC.

    `recurrence` should already be `validate`d; anything it would refuse raises
    ValueError here.
    """
    normalized, problem = validate(recurrence)
    if problem:
        raise ValueError(problem)
    after = _aware_utc(after_utc)
    tz = _zone(normalized["tz"])
    hour, minute = _parse_time(normalized["time"])
    if normalized["freq"] == "hourly":
        return _next_hourly(minute, tz, after)

    at = time(hour, minute)
    # Start a day early: the local date can trail the UTC one, and a time late on
    # the previous local day can still be ahead of `after`.
    first_day = after.astimezone(tz).date() - timedelta(days=1)
    for offset in range(_SEARCH_DAYS):
        day = first_day + timedelta(days=offset)
        if not _matches(normalized["freq"], normalized["days"], day):
            continue
        candidate = resolve_local(day, at, tz)
        if candidate > after:
            return candidate
    raise ValueError("no run found within a year")


def describe(recurrence: Dict[str, Any]) -> str:
    """A short phrase for logs and emails: "weekly on 1,3 at 09:00 Europe/London"."""
    normalized, problem = validate(recurrence)
    if problem:
        return "an unreadable recurrence"
    if normalized["freq"] == "hourly":
        return f"hourly at :{normalized['time'][3:]}"
    days = ",".join(str(d) for d in normalized["days"])
    on = f" on {days}" if days else ""
    return f"{normalized['freq']}{on} at {normalized['time']} {normalized['tz']}"
