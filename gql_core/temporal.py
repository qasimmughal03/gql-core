"""Typed temporal domain models and operations for GQL-Core.

Implements typed:
- Date (year, month, day)
- Time (hour, minute, second, microsecond, tz)
- DateTime (year, month, day, hour, minute, second, microsecond, tz)
- Duration (days, seconds, microseconds)
- Interval (start, end, start_inclusive, end_inclusive)

Supports:
- Before, After, On or before, On or after, Between
- Interval contains point, Interval overlaps, Interval intersection, Interval disjointness
- Elapsed duration, Temporal arithmetic (+, -)
- Timezone-aware vs timezone-naive semantics, explicit parsing, ISO-8601 formatting.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any


class TemporalTypeError(TypeError):
    """Raised when temporal operations receive incompatible or invalid types."""


@dataclass(frozen=True)
class Duration:
    """Represents an elapsed duration (days, seconds, microseconds)."""

    days: int = 0
    seconds: int = 0
    microseconds: int = 0

    @classmethod
    def from_timedelta(cls, td: dt.timedelta) -> Duration:
        return cls(days=td.days, seconds=td.seconds, microseconds=td.microseconds)

    @classmethod
    def from_iso(cls, text: str) -> Duration:
        """Parse ISO-8601 duration: P[n]Y[n]M[n]DT[n]H[n]M[n]S or P[n]D."""
        text = text.strip()
        m = re.match(
            r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$",
            text,
        )
        if not m:
            raise TemporalTypeError(f"Invalid ISO-8601 duration string: {text!r}")
        d = int(m.group("days") or 0)
        h = int(m.group("hours") or 0)
        mins = int(m.group("minutes") or 0)
        s_str = m.group("seconds") or "0"
        s = float(s_str)
        total_sec = h * 3600 + mins * 60 + int(s)
        micro = int(round((s - int(s)) * 1_000_000))
        return cls(days=d, seconds=total_sec, microseconds=micro)

    def to_timedelta(self) -> dt.timedelta:
        return dt.timedelta(days=self.days, seconds=self.seconds, microseconds=self.microseconds)

    @property
    def total_seconds(self) -> float:
        return self.days * 86400 + self.seconds + self.microseconds / 1_000_000.0

    def __add__(self, other: Any) -> Duration:
        if isinstance(other, Duration):
            td = self.to_timedelta() + other.to_timedelta()
            return Duration.from_timedelta(td)
        raise TemporalTypeError(f"Cannot add Duration and {type(other).__name__}")

    def __sub__(self, other: Any) -> Duration:
        if isinstance(other, Duration):
            td = self.to_timedelta() - other.to_timedelta()
            return Duration.from_timedelta(td)
        raise TemporalTypeError(f"Cannot subtract Duration and {type(other).__name__}")

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Duration):
            return self.total_seconds == other.total_seconds
        return False

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, Duration):
            return self.total_seconds < other.total_seconds
        raise TemporalTypeError(f"Cannot compare Duration and {type(other).__name__}")

    def __le__(self, other: Any) -> bool:
        if isinstance(other, Duration):
            return self.total_seconds <= other.total_seconds
        raise TemporalTypeError(f"Cannot compare Duration and {type(other).__name__}")

    def __gt__(self, other: Any) -> bool:
        if isinstance(other, Duration):
            return self.total_seconds > other.total_seconds
        raise TemporalTypeError(f"Cannot compare Duration and {type(other).__name__}")

    def __ge__(self, other: Any) -> bool:
        if isinstance(other, Duration):
            return self.total_seconds >= other.total_seconds
        raise TemporalTypeError(f"Cannot compare Duration and {type(other).__name__}")

    def __str__(self) -> str:
        return f"P{self.days}DT{self.seconds}S"


@dataclass(frozen=True)
class Date:
    """Represents a calendar date (year, month, day)."""

    year: int
    month: int
    day: int

    @classmethod
    def from_iso(cls, text: str) -> Date:
        try:
            d = dt.date.fromisoformat(text.strip())
            return cls(year=d.year, month=d.month, day=d.day)
        except Exception as e:
            raise TemporalTypeError(f"Invalid ISO-8601 date string: {text!r}") from e

    @classmethod
    def from_date(cls, d: dt.date) -> Date:
        return cls(year=d.year, month=d.month, day=d.day)

    def to_date(self) -> dt.date:
        return dt.date(self.year, self.month, self.day)

    def __add__(self, other: Any) -> Date:
        if isinstance(other, Duration):
            res = self.to_date() + other.to_timedelta()
            return Date.from_date(res)
        raise TemporalTypeError(f"Cannot add Date and {type(other).__name__}")

    def __sub__(self, other: Any) -> Any:
        if isinstance(other, Duration):
            res = self.to_date() - other.to_timedelta()
            return Date.from_date(res)
        if isinstance(other, Date):
            td = self.to_date() - other.to_date()
            return Duration.from_timedelta(td)
        raise TemporalTypeError(f"Cannot subtract {type(other).__name__} from Date")

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Date):
            return (self.year, self.month, self.day) == (other.year, other.month, other.day)
        return False

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, Date):
            return (self.year, self.month, self.day) < (other.year, other.month, other.day)
        raise TemporalTypeError(f"Cannot compare Date with {type(other).__name__}")

    def __le__(self, other: Any) -> bool:
        if isinstance(other, Date):
            return (self.year, self.month, self.day) <= (other.year, other.month, other.day)
        raise TemporalTypeError(f"Cannot compare Date with {type(other).__name__}")

    def __gt__(self, other: Any) -> bool:
        if isinstance(other, Date):
            return (self.year, self.month, self.day) > (other.year, other.month, other.day)
        raise TemporalTypeError(f"Cannot compare Date with {type(other).__name__}")

    def __ge__(self, other: Any) -> bool:
        if isinstance(other, Date):
            return (self.year, self.month, self.day) >= (other.year, other.month, other.day)
        raise TemporalTypeError(f"Cannot compare Date with {type(other).__name__}")

    def __str__(self) -> str:
        return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"


@dataclass(frozen=True)
class Time:
    """Represents a wall-clock time."""

    hour: int
    minute: int
    second: int = 0
    microsecond: int = 0
    tz_offset_minutes: int | None = None

    @classmethod
    def from_iso(cls, text: str) -> Time:
        try:
            t = dt.time.fromisoformat(text.strip())
            offset = None
            if t.tzinfo is not None:
                delta = t.tzinfo.utcoffset(None)
                if delta is not None:
                    offset = int(delta.total_seconds() // 60)
            return cls(hour=t.hour, minute=t.minute, second=t.second, microsecond=t.microsecond, tz_offset_minutes=offset)
        except Exception as e:
            raise TemporalTypeError(f"Invalid ISO-8601 time string: {text!r}") from e

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Time):
            return (self.hour, self.minute, self.second, self.microsecond, self.tz_offset_minutes) == (
                other.hour,
                other.minute,
                other.second,
                other.microsecond,
                other.tz_offset_minutes,
            )
        return False

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, Time):
            if (self.tz_offset_minutes is None) != (other.tz_offset_minutes is None):
                raise TemporalTypeError("Cannot compare timezone-aware Time with timezone-naive Time")
            return (self.hour, self.minute, self.second, self.microsecond) < (
                other.hour,
                other.minute,
                other.second,
                other.microsecond,
            )
        raise TemporalTypeError(f"Cannot compare Time with {type(other).__name__}")

    def __le__(self, other: Any) -> bool:
        return self == other or self < other

    def __gt__(self, other: Any) -> bool:
        if isinstance(other, Time):
            return not (self <= other)
        raise TemporalTypeError(f"Cannot compare Time with {type(other).__name__}")

    def __ge__(self, other: Any) -> bool:
        return self == other or self > other

    def __str__(self) -> str:
        base = f"{self.hour:02d}:{self.minute:02d}:{self.second:02d}"
        if self.microsecond:
            base += f".{self.microsecond:06d}"
        if self.tz_offset_minutes is not None:
            sign = "+" if self.tz_offset_minutes >= 0 else "-"
            total = abs(self.tz_offset_minutes)
            base += f"{sign}{total // 60:02d}:{total % 60:02d}"
        return base


@dataclass(frozen=True)
class DateTime:
    """Represents a date and time timestamp."""

    year: int
    month: int
    day: int
    hour: int = 0
    minute: int = 0
    second: int = 0
    microsecond: int = 0
    tz_offset_minutes: int | None = None

    @classmethod
    def from_iso(cls, text: str) -> DateTime:
        try:
            d = dt.datetime.fromisoformat(text.strip())
            offset = None
            if d.tzinfo is not None:
                delta = d.tzinfo.utcoffset(None)
                if delta is not None:
                    offset = int(delta.total_seconds() // 60)
            return cls(
                year=d.year,
                month=d.month,
                day=d.day,
                hour=d.hour,
                minute=d.minute,
                second=d.second,
                microsecond=d.microsecond,
                tz_offset_minutes=offset,
            )
        except Exception as e:
            raise TemporalTypeError(f"Invalid ISO-8601 datetime string: {text!r}") from e

    @classmethod
    def from_datetime(cls, d: dt.datetime) -> DateTime:
        offset = None
        if d.tzinfo is not None:
            delta = d.tzinfo.utcoffset(None)
            if delta is not None:
                offset = int(delta.total_seconds() // 60)
        return cls(
            year=d.year,
            month=d.month,
            day=d.day,
            hour=d.hour,
            minute=d.minute,
            second=d.second,
            microsecond=d.microsecond,
            tz_offset_minutes=offset,
        )

    def to_datetime(self) -> dt.datetime:
        tz = None
        if self.tz_offset_minutes is not None:
            tz = dt.timezone(dt.timedelta(minutes=self.tz_offset_minutes))
        return dt.datetime(
            self.year,
            self.month,
            self.day,
            self.hour,
            self.minute,
            self.second,
            self.microsecond,
            tzinfo=tz,
        )

    def __add__(self, other: Any) -> DateTime:
        if isinstance(other, Duration):
            res = self.to_datetime() + other.to_timedelta()
            return DateTime.from_datetime(res)
        raise TemporalTypeError(f"Cannot add DateTime and {type(other).__name__}")

    def __sub__(self, other: Any) -> Any:
        if isinstance(other, Duration):
            res = self.to_datetime() - other.to_timedelta()
            return DateTime.from_datetime(res)
        if isinstance(other, DateTime):
            if (self.tz_offset_minutes is None) != (other.tz_offset_minutes is None):
                raise TemporalTypeError("Cannot subtract timezone-aware DateTime and timezone-naive DateTime")
            td = self.to_datetime() - other.to_datetime()
            return Duration.from_timedelta(td)
        raise TemporalTypeError(f"Cannot subtract {type(other).__name__} from DateTime")

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, DateTime):
            if (self.tz_offset_minutes is None) != (other.tz_offset_minutes is None):
                return False
            return self.to_datetime() == other.to_datetime()
        return False

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, DateTime):
            if (self.tz_offset_minutes is None) != (other.tz_offset_minutes is None):
                raise TemporalTypeError("Cannot compare timezone-aware DateTime with timezone-naive DateTime")
            return self.to_datetime() < other.to_datetime()
        raise TemporalTypeError(f"Cannot compare DateTime with {type(other).__name__}")

    def __le__(self, other: Any) -> bool:
        return self == other or self < other

    def __gt__(self, other: Any) -> bool:
        if isinstance(other, DateTime):
            return not (self <= other)
        raise TemporalTypeError(f"Cannot compare DateTime with {type(other).__name__}")

    def __ge__(self, other: Any) -> bool:
        return self == other or self > other

    def __str__(self) -> str:
        s = f"{self.year:04d}-{self.month:02d}-{self.day:02d}T{self.hour:02d}:{self.minute:02d}:{self.second:02d}"
        if self.microsecond:
            s += f".{self.microsecond:06d}"
        if self.tz_offset_minutes is not None:
            sign = "+" if self.tz_offset_minutes >= 0 else "-"
            total = abs(self.tz_offset_minutes)
            s += f"{sign}{total // 60:02d}:{total % 60:02d}"
        return s


@dataclass(frozen=True)
class Interval:
    """Represents a bounded or open temporal interval [start, end]."""

    start: Date | DateTime | None
    end: Date | DateTime | None
    start_inclusive: bool = True
    end_inclusive: bool = True

    def __post_init__(self) -> None:
        if self.start is not None and self.end is not None:
            if type(self.start) is not type(self.end):
                raise TemporalTypeError("Interval start and end must have the same temporal type (Date or DateTime)")
            if self.start > self.end:
                raise TemporalTypeError(f"Interval start ({self.start}) cannot be after end ({self.end})")

    def contains(self, point: Date | DateTime) -> bool:
        """Returns True if point lies within this interval."""
        if self.start is not None:
            if type(point) is not type(self.start):
                raise TemporalTypeError("Point type does not match interval boundary type")
            if self.start_inclusive and point < self.start:
                return False
            if not self.start_inclusive and point <= self.start:
                return False

        if self.end is not None:
            if type(point) is not type(self.end):
                raise TemporalTypeError("Point type does not match interval boundary type")
            if self.end_inclusive and point > self.end:
                return False
            if not self.end_inclusive and point >= self.end:
                return False

        return True

    def overlaps(self, other: Interval) -> bool:
        """Returns True if two intervals share at least one point."""
        if self.start is not None and other.end is not None:
            if type(self.start) is not type(other.end):
                raise TemporalTypeError("Interval types do not match")
            if self.start > other.end:
                return False
            if self.start == other.end and not (self.start_inclusive and other.end_inclusive):
                return False

        if self.end is not None and other.start is not None:
            if type(self.end) is not type(other.start):
                raise TemporalTypeError("Interval types do not match")
            if self.end < other.start:
                return False
            if self.end == other.start and not (self.end_inclusive and other.start_inclusive):
                return False

        return True

    def is_disjoint(self, other: Interval) -> bool:
        return not self.overlaps(other)

    def intersection(self, other: Interval) -> Interval | None:
        """Returns the intersection of two intervals, or None if disjoint."""
        if not self.overlaps(other):
            return None

        # Determine start
        if self.start is None:
            new_start = other.start
            new_start_inc = other.start_inclusive
        elif other.start is None:
            new_start = self.start
            new_start_inc = self.start_inclusive
        else:
            if self.start > other.start:
                new_start = self.start
                new_start_inc = self.start_inclusive
            elif other.start > self.start:
                new_start = other.start
                new_start_inc = other.start_inclusive
            else:
                new_start = self.start
                new_start_inc = self.start_inclusive and other.start_inclusive

        # Determine end
        if self.end is None:
            new_end = other.end
            new_end_inc = other.end_inclusive
        elif other.end is None:
            new_end = self.end
            new_end_inc = self.end_inclusive
        else:
            if self.end < other.end:
                new_end = self.end
                new_end_inc = self.end_inclusive
            elif other.end < self.end:
                new_end = other.end
                new_end_inc = other.end_inclusive
            else:
                new_end = self.end
                new_end_inc = self.end_inclusive and other.end_inclusive

        return Interval(
            start=new_start,
            end=new_end,
            start_inclusive=new_start_inc,
            end_inclusive=new_end_inc,
        )


def coerce_temporal(val: Any) -> Any:
    """Safely coerce strings or datetime primitives into typed temporal instances."""
    if isinstance(val, (Date, Time, DateTime, Duration, Interval)):
        return val
    if isinstance(val, dt.datetime):
        return DateTime.from_datetime(val)
    if isinstance(val, dt.date):
        return Date.from_date(val)
    if isinstance(val, dt.timedelta):
        return Duration.from_timedelta(val)
    if isinstance(val, str):
        val = val.strip()
        # Attempt ISO datetime
        if "T" in val:
            try:
                return DateTime.from_iso(val)
            except Exception:
                pass
        # Attempt ISO date
        if re.match(r"^\d{4}-\d{2}-\d{2}$", val):
            try:
                return Date.from_iso(val)
            except Exception:
                pass
        # Attempt ISO time
        if re.match(r"^\d{2}:\d{2}(?::\d{2})?", val):
            try:
                return Time.from_iso(val)
            except Exception:
                pass
        # Attempt ISO duration
        if val.startswith("P"):
            try:
                return Duration.from_iso(val)
            except Exception:
                pass
    return val
