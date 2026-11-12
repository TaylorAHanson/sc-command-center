"""Tests for when a schedule runs next (services/recurrence.py).

Pure functions, no database. Pinned here:

- what `validate` accepts, how it normalizes, and the sentence for each refusal;
- daily, weekly and monthly times in the schedule's own zone, including weekly
  days that wrap past Sunday and monthly days clamped to the month's end;
- hourly runs at the local minute in zones with whole, half and quarter hour
  offsets;
- daylight saving both ways: a missing time runs when the clock jumps, a repeated
  one runs once, at its first occurrence, and hourly keeps to real hours;
- that the answer is always strictly after the instant given, and aware UTC.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from services import recurrence as rec  # noqa: E402

NY = "America/New_York"
LONDON = "Europe/London"


def utc(*parts):
    return datetime(*parts, tzinfo=timezone.utc)


def nxt(after, **recurrence):
    return rec.next_run(recurrence, after)


def runs(start, count, **recurrence):
    out, at = [], start
    for _ in range(count):
        at = rec.next_run(recurrence, at)
        out.append(at)
    return out


# --- validation ------------------------------------------------------------------

def test_a_valid_recurrence_is_normalized():
    got, problem = rec.validate({"freq": "Weekly", "days": [7, 1, 3, 1], "time": "9:05", "tz": LONDON})
    assert problem is None
    assert got == {"freq": "weekly", "days": [1, 3, 7], "time": "09:05", "tz": LONDON}


def test_hourly_and_daily_ignore_days():
    for freq in ("hourly", "daily"):
        got, problem = rec.validate({"freq": freq, "days": [99, "x"], "time": "00:15", "tz": NY})
        assert problem is None and got["days"] == []


def test_a_missing_zone_is_utc():
    got, problem = rec.validate({"freq": "daily", "time": "06:00"})
    assert problem is None and got["tz"] == "UTC"


def test_each_refusal_is_a_sentence():
    cases = [
        (None, "hourly, daily, weekly or monthly"),
        ({"freq": "yearly", "time": "09:00"}, "hourly, daily, weekly or monthly"),
        ({"freq": "daily"}, "HH:MM"),
        ({"freq": "daily", "time": "24:00"}, "HH:MM"),
        ({"freq": "daily", "time": "09:60"}, "HH:MM"),
        ({"freq": "daily", "time": "9am"}, "HH:MM"),
        ({"freq": "weekly", "time": "09:00"}, "weekday"),
        ({"freq": "weekly", "days": [], "time": "09:00"}, "weekday"),
        ({"freq": "weekly", "days": [0], "time": "09:00"}, "weekday"),
        ({"freq": "weekly", "days": [8], "time": "09:00"}, "weekday"),
        ({"freq": "weekly", "days": [True], "time": "09:00"}, "weekday"),
        ({"freq": "weekly", "days": ["1"], "time": "09:00"}, "weekday"),
        ({"freq": "weekly", "days": 1, "time": "09:00"}, "weekday"),
        ({"freq": "monthly", "days": [32], "time": "09:00"}, "day of the month"),
        ({"freq": "monthly", "days": [0], "time": "09:00"}, "day of the month"),
        ({"freq": "daily", "time": "09:00", "tz": "Mars/Olympus"}, "isn't a time zone"),
        ({"freq": "daily", "time": "09:00", "tz": "../../etc/passwd"}, "isn't a time zone"),
        ({"freq": "daily", "time": "09:00", "tz": "/etc/localtime"}, "isn't a time zone"),
        ({"freq": "daily", "time": "09:00", "tz": "x" * 200}, "isn't a time zone"),
    ]
    for given, phrase in cases:
        got, problem = rec.validate(given)
        assert got is None, given
        assert phrase in problem and problem.endswith("."), (given, problem)


def test_next_run_refuses_what_validate_refuses():
    try:
        rec.next_run({"freq": "weekly", "time": "09:00"}, utc(2026, 1, 1))
    except ValueError as e:
        assert "weekday" in str(e)
    else:
        raise AssertionError("an invalid recurrence produced a time")


# --- daily, weekly, monthly ---------------------------------------------------------

def test_daily_is_the_local_time_in_its_zone():
    # 09:00 in New York in November is 14:00 UTC.
    assert nxt(utc(2026, 11, 12, 13, 59), freq="daily", time="09:00", tz=NY) == utc(2026, 11, 12, 14, 0)
    assert nxt(utc(2026, 11, 12, 14, 0), freq="daily", time="09:00", tz=NY) == utc(2026, 11, 13, 14, 0)


def test_the_answer_is_strictly_after_and_aware_utc():
    at = utc(2026, 6, 1, 8, 0)
    got = nxt(at, freq="daily", time="08:00", tz="UTC")
    assert got == utc(2026, 6, 2, 8, 0)
    assert got.tzinfo is not None and got.utcoffset() == timedelta(0)


def test_a_naive_instant_is_read_as_utc():
    assert nxt(datetime(2026, 6, 1, 7, 0), freq="daily", time="08:00", tz="UTC") == utc(2026, 6, 1, 8, 0)


def test_a_late_local_time_on_the_previous_local_day_is_found():
    # 23:30 in Los Angeles on the 11th is 07:30 UTC on the 12th.
    got = nxt(utc(2026, 11, 12, 7, 0), freq="daily", time="23:30", tz="America/Los_Angeles")
    assert got == utc(2026, 11, 12, 7, 30)


def test_weekly_days_wrap_past_sunday():
    # 2026-11-13 is a Friday. Monday and Wednesday are next week.
    got = runs(utc(2026, 11, 13, 12, 0), 3, freq="weekly", days=[1, 3], time="09:00", tz="UTC")
    assert got == [utc(2026, 11, 16, 9, 0), utc(2026, 11, 18, 9, 0), utc(2026, 11, 23, 9, 0)]
    assert [d.isoweekday() for d in got] == [1, 3, 1]


def test_weekly_on_sunday_is_seven():
    got = nxt(utc(2026, 11, 13), freq="weekly", days=[7], time="10:00", tz="UTC")
    assert got == utc(2026, 11, 15, 10, 0) and got.isoweekday() == 7


def test_weekly_follows_the_local_weekday_not_the_utc_one():
    # Monday 08:00 in Tokyo is Sunday 23:00 UTC.
    got = nxt(utc(2026, 11, 13), freq="weekly", days=[1], time="08:00", tz="Asia/Tokyo")
    assert got == utc(2026, 11, 15, 23, 0)


def test_monthly_days_are_clamped_to_the_month_end():
    got = runs(utc(2026, 1, 31, 10, 0), 4, freq="monthly", days=[31], time="09:00", tz="UTC")
    assert got == [utc(2026, 2, 28, 9, 0), utc(2026, 3, 31, 9, 0), utc(2026, 4, 30, 9, 0), utc(2026, 5, 31, 9, 0)]


def test_monthly_in_a_leap_february():
    assert nxt(utc(2028, 2, 1), freq="monthly", days=[30], time="00:00", tz="UTC") == utc(2028, 2, 29, 0, 0)


def test_two_days_that_clamp_to_one_run_once():
    got = runs(utc(2026, 2, 1), 3, freq="monthly", days=[30, 31], time="12:00", tz="UTC")
    assert got == [utc(2026, 2, 28, 12, 0), utc(2026, 3, 30, 12, 0), utc(2026, 3, 31, 12, 0)]


def test_monthly_crosses_the_year():
    assert nxt(utc(2026, 12, 15), freq="monthly", days=[1], time="06:00", tz="UTC") == utc(2027, 1, 1, 6, 0)


# --- hourly ------------------------------------------------------------------------

def test_hourly_uses_only_the_minute():
    got = runs(utc(2026, 11, 12, 10, 20), 3, freq="hourly", time="17:15", tz="UTC")
    assert got == [utc(2026, 11, 12, 11, 15), utc(2026, 11, 12, 12, 15), utc(2026, 11, 12, 13, 15)]


def test_hourly_in_half_and_quarter_hour_zones():
    # Kolkata is UTC+5:30, so :15 local is :45 UTC; Kathmandu is +5:45, so :00 local is :15 UTC.
    assert nxt(utc(2026, 11, 12, 10, 0), freq="hourly", time="00:15", tz="Asia/Kolkata") == utc(2026, 11, 12, 10, 45)
    assert nxt(utc(2026, 11, 12, 10, 0), freq="hourly", time="00:00", tz="Asia/Kathmandu") == utc(2026, 11, 12, 10, 15)
    # St John's is UTC-3:30 in November.
    assert nxt(utc(2026, 11, 12, 10, 0), freq="hourly", time="00:00", tz="America/St_Johns") == utc(2026, 11, 12, 10, 30)


# --- daylight saving ---------------------------------------------------------------

def test_a_time_that_doesnt_exist_runs_when_the_clock_jumps():
    # New York, 2026-03-08: 02:00 EST becomes 03:00 EDT at 07:00 UTC, so 02:30 never happens.
    got = runs(utc(2026, 3, 7, 12, 0), 2, freq="daily", time="02:30", tz=NY)
    assert got == [utc(2026, 3, 8, 7, 0), utc(2026, 3, 9, 6, 30)]


def test_a_missing_time_in_london_runs_at_two():
    # London, 2026-03-29: 01:00 GMT becomes 02:00 BST at 01:00 UTC.
    got = nxt(utc(2026, 3, 28, 12, 0), freq="daily", time="01:30", tz=LONDON)
    assert got == utc(2026, 3, 29, 1, 0)


def test_a_time_that_happens_twice_runs_once_at_the_first():
    # New York, 2026-11-01: 02:00 EDT becomes 01:00 EST at 06:00 UTC, so 01:30 happens at 05:30 and 06:30 UTC.
    got = runs(utc(2026, 10, 31, 12, 0), 2, freq="daily", time="01:30", tz=NY)
    assert got == [utc(2026, 11, 1, 5, 30), utc(2026, 11, 2, 6, 30)]


def test_a_weekly_run_keeps_its_local_time_across_the_change():
    # Sunday 09:00 in New York, before and after the November change.
    got = runs(utc(2026, 10, 24), 2, freq="weekly", days=[7], time="09:00", tz=NY)
    assert got == [utc(2026, 10, 25, 13, 0), utc(2026, 11, 1, 14, 0)]


def test_hourly_keeps_to_real_hours_when_the_clock_jumps():
    # At the spring change the local 02:30 never happens; the hour after 01:30 EST is 03:30 EDT.
    got = runs(utc(2026, 3, 8, 6, 0), 3, freq="hourly", time="00:30", tz=NY)
    assert got == [utc(2026, 3, 8, 6, 30), utc(2026, 3, 8, 7, 30), utc(2026, 3, 8, 8, 30)]
    assert [g - a for g, a in zip(got[1:], got)] == [timedelta(hours=1)] * 2


def test_hourly_runs_both_repeated_hours_when_the_clock_falls_back():
    # 01:30 local happens twice on 2026-11-01; an hourly run is every real hour.
    got = runs(utc(2026, 11, 1, 5, 0), 3, freq="hourly", time="00:30", tz=NY)
    assert got == [utc(2026, 11, 1, 5, 30), utc(2026, 11, 1, 6, 30), utc(2026, 11, 1, 7, 30)]


def test_resolve_local_handles_a_half_hour_shift():
    # Lord Howe Island moves its clocks by 30 minutes: 02:00 becomes 02:30 on 2026-10-04.
    from datetime import date, time
    import zoneinfo
    tz = zoneinfo.ZoneInfo("Australia/Lord_Howe")
    got = rec.resolve_local(date(2026, 10, 4), time(2, 15), tz)
    assert got.astimezone(tz).replace(tzinfo=None) == datetime(2026, 10, 4, 2, 30)


def test_describe_says_what_it_is():
    assert rec.describe({"freq": "hourly", "time": "07:05"}) == "hourly at :05"
    assert rec.describe({"freq": "weekly", "days": [3, 1], "time": "09:00", "tz": LONDON}) == \
        "weekly on 1,3 at 09:00 Europe/London"
    assert rec.describe({"freq": "nope"}) == "an unreadable recurrence"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
