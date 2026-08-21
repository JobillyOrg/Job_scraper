from __future__ import annotations

import logging
import os
import re
from typing import Any

from job_scraper.http import Http
from job_scraper.models import Job
from job_scraper.normalize import format_posted_date, html_to_text, looks_usa

logger = logging.getLogger(__name__)

BASE_URL = os.environ.get("FREEHIRE_API_URL", "https://freehire.me").rstrip("/")
SEARCH_PATHS = ("/api/v1/agent/jobs/search", "/api/v1/jobs/search")
PAGE_SIZE = 100


def fetch_freehire(
    http: Http,
    query: str,
    location: str = "United States",
    results_wanted: int = 100,
    hours_old: int | None = 168,
    usa_only: bool = True,
) -> list[Job]:
    wanted = max(1, int(results_wanted or 100))
    params: dict[str, Any] = {
        "q": (query or "").strip(),
        "limit": min(PAGE_SIZE, wanted),
        "include_description": "true",
        "description_format": "text",
        "semantic_ratio": "0",
    }
    if hours_old:
        params["posted_within_days"] = max(1, int(hours_old) // 24)
    if usa_only:
        params["countries"] = "us"
    city = _city_from_location(location)
    if city:
        params["cities"] = city

    items: list[dict[str, Any]] = []
    offset = 0
    path = SEARCH_PATHS[0]
    while len(items) < wanted:
        page_params = dict(params)
        page_params["limit"] = min(PAGE_SIZE, wanted - len(items))
        page_params["offset"] = offset
        payload, path = _search(http, path, page_params)
        batch = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(batch, list) or not batch:
            break
        items.extend(batch)
        meta = payload.get("meta") if isinstance(payload, dict) else {}
        total = int((meta or {}).get("total") or 0)
        offset += len(batch)
        if offset >= total or len(batch) < page_params["limit"]:
            break
        if offset > 5000:
            break

    jobs: list[Job] = []
    for item in items[:wanted]:
        if not isinstance(item, dict):
            continue
        job = _to_job(item)
        if not job.title:
            continue
        if usa_only and not looks_usa(job.location, job.is_remote):
            continue
        jobs.append(job)
    logger.info("Freehire returned %s jobs for %r", len(jobs), query)
    return jobs


def _search(http: Http, path: str, params: dict[str, Any]) -> tuple[dict[str, Any], str]:
    tried = [path] + [p for p in SEARCH_PATHS if p != path]
    last: dict[str, Any] = {}
    for candidate in tried:
        response = http.get(f"{BASE_URL}{candidate}", params=params)
        if response.status_code in {400, 404} and candidate == SEARCH_PATHS[0]:
            continue
        response.raise_for_status()
        payload = response.json() if response.content else {}
        return payload if isinstance(payload, dict) else {"data": payload}, candidate
    return last, path


def _to_job(item: dict[str, Any]) -> Job:
    enrichment = item.get("enrichment") or {}
    if not isinstance(enrichment, dict):
        enrichment = {}
    location = item.get("location") or ""
    if not location:
        cities = item.get("cities") or []
        countries = item.get("countries") or []
        location = ", ".join(str(part) for part in [*cities, *countries] if part)
    work_mode = str(item.get("work_mode") or enrichment.get("work_mode") or "").lower()
    apply = item.get("url") or ""
    slug = item.get("public_slug") or ""
    salary = _salary(enrichment)
    return Job(
        title=(item.get("title") or "").strip(),
        company=(item.get("company") or "").strip(),
        source="freehire",
        url=apply or (f"{BASE_URL}/jobs/{slug}" if slug else ""),
        location=location,
        is_remote=work_mode == "remote" or "remote" in location.lower(),
        job_type=str(enrichment.get("employment_type") or ""),
        department=str(enrichment.get("category") or ""),
        date_posted=format_posted_date(item.get("posted_at") or item.get("created_at")),
        description=html_to_text(item.get("description")),
        salary=salary,
        apply_url=apply or (f"{BASE_URL}/jobs/{slug}" if slug else ""),
        company_slug=str(item.get("company_slug") or ""),
    )


def _salary(enrichment: dict[str, Any]) -> str:
    low = enrichment.get("salary_min")
    high = enrichment.get("salary_max")
    currency = enrichment.get("salary_currency") or ""
    if low and high:
        return f"{low}-{high} {currency}".strip()
    if low:
        return f"{low} {currency}".strip()
    return ""


def _city_from_location(location: str) -> str:
    text = (location or "").strip()
    if not text or re.search(r"united\s+states|^usa$|^us$", text, re.IGNORECASE):
        return ""
    return text.split(",")[0].strip()
