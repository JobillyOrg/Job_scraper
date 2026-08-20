from __future__ import annotations

import html
import re
from datetime import datetime, timezone
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


def format_posted_date(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return ""
    if re.fullmatch(r"\d{10,13}", text):
        stamp = int(text)
        if stamp > 10_000_000_000:
            stamp //= 1000
        try:
            return datetime.fromtimestamp(stamp, tz=timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return text
    iso = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso).date().isoformat()
    except ValueError:
        pass
    cleaned = re.sub(r"^posted\s+", "", text, flags=re.IGNORECASE).strip()
    return cleaned
