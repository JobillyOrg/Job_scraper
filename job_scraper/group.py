from __future__ import annotations

import re
from typing import Any

_SPACE = re.compile(r"\s+")


def group_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge the same role at different sites into one listing with location links."""
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    order: list[tuple[str, str, str]] = []

    for job in jobs:
        key = (
            (job.get("source") or "").strip().lower(),
            (job.get("company") or "").strip().lower(),
            _norm_title(job.get("title") or ""),
        )
        if key not in grouped:
            grouped[key] = _base(job)
            order.append(key)
        grouped[key] = _merge(grouped[key], job)

    return [grouped[key] for key in order]


def _norm_title(title: str) -> str:
    return _SPACE.sub(" ", (title or "").strip().lower())


def _base(job: dict[str, Any]) -> dict[str, Any]:
    locations = _locations_from(job)
    merged = dict(job)
    merged["locations"] = locations
    merged["location"] = _location_text(locations)
    merged["url"] = locations[0]["url"] if locations else (job.get("url") or job.get("apply_url") or "")
    merged["apply_url"] = merged["url"]
    return merged


def _merge(current: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    seen = {(loc["label"].lower(), loc["url"]) for loc in current["locations"]}
    for loc in _locations_from(job):
        pair = (loc["label"].lower(), loc["url"])
        if pair in seen:
            continue
        current["locations"].append(loc)
        seen.add(pair)
    current["location"] = _location_text(current["locations"])
    incoming = (job.get("description") or "").strip()
    if len(incoming) > len(current.get("description") or ""):
        current["description"] = incoming
    if job.get("is_remote"):
        current["is_remote"] = True
    if not current.get("date_posted") and job.get("date_posted"):
        current["date_posted"] = job["date_posted"]
    elif job.get("date_posted") and str(job["date_posted"]) > str(current.get("date_posted") or ""):
        current["date_posted"] = job["date_posted"]
    return current


def _locations_from(job: dict[str, Any]) -> list[dict[str, str]]:
    url = (job.get("apply_url") or job.get("url") or "").strip()
    raw = (job.get("location") or "").strip()
    if job.get("locations"):
        out = []
        for item in job["locations"]:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            href = str(item.get("url") or url).strip()
            if label:
                out.append({"label": label, "url": href})
        if out:
            return out
    labels = [part.strip() for part in re.split(r"\s*[|;/]\s*|\s+·\s+", raw) if part.strip()]
    if not labels:
        if job.get("is_remote"):
            labels = ["Remote"]
        elif url:
            labels = ["See posting"]
    return [{"label": label, "url": url} for label in labels]


def _location_text(locations: list[dict[str, str]]) -> str:
    seen: list[str] = []
    used: set[str] = set()
    for loc in locations:
        label = loc["label"]
        key = label.lower()
        if key in used:
            continue
        used.add(key)
        seen.append(label)
    return " · ".join(seen)
