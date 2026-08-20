from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any

US_LOCATION = re.compile(
    r"""
    \b(united\s+states|u\.s\.a?\.?|usa|us)\b
    | \bus[- ]
    | ,\s*(AL|AK|AZ|AR|CA|CO|CT|DC|DE|FL|GA|HI|IA|ID|IL|IN|KS|KY|LA|MA|MD|ME|MI|MN|MO|MS|MT|NC|ND|NE|NH|NJ|NM|NV|NY|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VA|VT|WA|WI|WV|WY)\b
    | \b(remote|anywhere|united states only|us only)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

NON_US_COUNTRY = re.compile(
    r"\b(india|germany|france|uk|united kingdom|canada|australia|singapore|"
    r"ireland|netherlands|spain|brazil|mexico|japan|poland|sweden|israel)\b",
    re.IGNORECASE,
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    decoded = html.unescape(html.unescape(value))
    parser = _TextExtractor()
    try:
        parser.feed(decoded)
        parser.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", decoded)
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def looks_usa(location: str, is_remote: bool | None = None) -> bool:
    loc = (location or "").strip()
    if loc and NON_US_COUNTRY.search(loc) and not US_LOCATION.search(loc):
        return False
    if is_remote:
        return True
    if not loc:
        return True
    if US_LOCATION.search(loc):
        return True
    # City-only strings like "Austin" or "New York" are kept.
    return True


def join_location(*parts: str | None) -> str:
    values = [p.strip() for p in parts if p and str(p).strip() and str(p).lower() not in {"nan", "none"}]
    return ", ".join(values)


_RELATIVE_HOURS = re.compile(
    r"""
    ^(?:posted\s+)?
    (?:
        (?P<just>just\s+now|moments?\s+ago|now)
        | (?P<minutes>an?|1|\d+)\s+minutes?\s+ago
        | (?P<hours>an?|1|\d+)\s+hours?\s+ago
    )
    $
    """,
    re.IGNORECASE | re.VERBOSE,
)


def format_posted_date(value: Any) -> str:
    """Store a date, or an ISO timestamp when the job is less than 24 hours old."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return _from_datetime(value, has_clock=_has_clock(value))
    if isinstance(value, date):
        return value.isoformat()

    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return ""

    relative = _relative_under_24h(text)
    if relative is not None:
        return _from_datetime(datetime.now(timezone.utc) - relative, has_clock=True)

    if re.fullmatch(r"\d{10,13}", text):
        stamp = int(text)
        if stamp > 10_000_000_000:
            stamp //= 1000
        try:
            return _from_datetime(datetime.fromtimestamp(stamp, tz=timezone.utc), has_clock=True)
        except (OverflowError, OSError, ValueError):
            return text

    iso = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError:
        parsed = None
    if parsed is not None:
        has_clock = bool(re.search(r"T\d{2}:|\d{2}:\d{2}", iso))
        if parsed.tzinfo is None and has_clock:
            parsed = parsed.replace(tzinfo=timezone.utc)
        if has_clock:
            return _from_datetime(parsed, has_clock=True)
        return parsed.date().isoformat()

    cleaned = re.sub(r"^posted\s+", "", text, flags=re.IGNORECASE).strip()
    return cleaned


def _has_clock(value: datetime) -> bool:
    return not (value.hour == 0 and value.minute == 0 and value.second == 0 and value.microsecond == 0)


def _from_datetime(value: datetime, has_clock: bool) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    aware = value.astimezone(timezone.utc)
    if has_clock:
        age = datetime.now(timezone.utc) - aware
        if timedelta(0) <= age < timedelta(hours=24):
            return aware.isoformat(timespec="seconds")
    return aware.date().isoformat()


def _relative_under_24h(text: str) -> timedelta | None:
    cleaned = re.sub(r"^posted\s+", "", text.strip(), flags=re.IGNORECASE)
    match = _RELATIVE_HOURS.fullmatch(cleaned)
    if not match:
        return None
    if match.group("just"):
        return timedelta(0)
    if match.group("minutes"):
        raw = match.group("minutes").lower()
        minutes = 1 if raw in {"a", "an", "1"} else int(raw)
        if minutes >= 24 * 60:
            return None
        return timedelta(minutes=minutes)
    if match.group("hours"):
        raw = match.group("hours").lower()
        hours = 1 if raw in {"a", "an", "1"} else int(raw)
        if hours >= 24:
            return None
        return timedelta(hours=hours)
    return None
