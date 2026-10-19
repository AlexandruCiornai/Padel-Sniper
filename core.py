"""Pure booking rules, kept free of Flask/Playwright so they can be unit tested."""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Bucharest")
BOOKING_WINDOW = timedelta(days=14)   # Calendis opens a slot exactly 14 days ahead
LEAD_TIME = timedelta(minutes=2)      # log in and load the calendar this much earlier

_HOUR_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def slot_datetime(target_date: str, target_hour: str) -> datetime:
    """'2026-06-29' + '15:00' -> the slot start on the Bucharest clock.

    Raises ValueError for a malformed date or hour.
    """
    match = _HOUR_RE.match(target_hour)
    if not match:
        raise ValueError(f"invalid hour {target_hour!r}, expected HH:MM")
    day = datetime.strptime(target_date, "%Y-%m-%d")
    return day.replace(hour=int(match[1]), minute=int(match[2]), tzinfo=TZ)


def slot_opens_at(slot: datetime) -> datetime:
    """When the slot becomes bookable: same wall-clock time, 14 calendar days earlier.

    Aware-datetime arithmetic in Python keeps the wall clock, so this stays
    correct when a DST change falls inside the 14 days.
    """
    return slot - BOOKING_WINDOW


def bot_starts_at(slot: datetime) -> datetime:
    """When the scheduled job should launch the browser."""
    return slot_opens_at(slot) - LEAD_TIME


def is_valid_pin(pin: str) -> bool:
    """The login screen has a 4-digit keypad, so only 4-digit PINs can ever be entered."""
    return len(pin) == 4 and pin.isascii() and pin.isdigit()
