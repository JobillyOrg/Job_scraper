from __future__ import annotations

import logging
from typing import Any, Iterable

from job_scraper.models import Job
from job_scraper.normalize import format_posted_date, join_location

logger = logging.getLogger(__name__)

BOARD_SITES = ("indeed", "linkedin", "zip_recruiter", "google", "glassdoor")


def scrape_boards(
    query: str,
    location: str = "United States",
    site_name: Iterable[str] | None = None,
    country_indeed: str = "USA",
    results_wanted: int = 100,
    hours_old: int | None = 168,
    linkedin_fetch_description: bool = False,
    proxies: list[str] | None = None,
) -> list[Job]:
    try:
        from jobspy import scrape_jobs
    except ImportError as exc:
        raise RuntimeError("python-jobspy is not installed. Run: pip install python-jobspy") from exc

    sites = [s for s in (site_name or BOARD_SITES) if s in BOARD_SITES or s == "linkedin"]
    if not sites:
        return []

    kwargs: dict[str, Any] = {
        "site_name": sites,
        "search_term": query,
        "location": location,
        "results_wanted": results_wanted,
        "country_indeed": country_indeed,
        "linkedin_fetch_description": linkedin_fetch_description,
    }
    if hours_old is not None:
        kwargs["hours_old"] = hours_old
    if proxies:
        kwargs["proxies"] = proxies

    logger.info("Scraping boards %s for %r in %r", sites, query, location)
    try:
        frame = scrape_jobs(**kwargs)
    except TypeError:
        kwargs.pop("hours_old", None)
        frame = scrape_jobs(**kwargs)

    if frame is None or frame.empty:
        return []

    jobs: list[Job] = []
    for row in frame.to_dict(orient="records"):
        jobs.append(_from_jobspy(row))
    return jobs


def _from_jobspy(row: dict[str, Any]) -> Job:
    def val(*keys: str) -> str:
        for key in keys:
            value = row.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text and text.lower() not in {"nan", "none"}:
                return text
        return ""

    remote = row.get("is_remote")
    is_remote: bool | None
    if remote is True or str(remote).lower() in {"true", "1"}:
        is_remote = True
    elif remote is False or str(remote).lower() in {"false", "0"}:
        is_remote = False
    else:
        is_remote = None

    salary = val("salary_source", "min_amount", "compensation")
    if val("min_amount") and val("max_amount"):
        salary = f"{val('min_amount')}-{val('max_amount')} {val('interval')} {val('currency')}".strip()

    location = val("location") or join_location(val("city"), val("state"), val("country"))

    return Job(
        title=val("title"),
        company=val("company"),
        source=val("site") or "jobspy",
        url=val("job_url", "job_url_direct"),
        location=location,
        is_remote=is_remote,
        job_type=val("job_type"),
        date_posted=format_posted_date(val("date_posted")),
        description=val("description"),
        salary=salary,
        apply_url=val("job_url_direct", "job_url"),
    )
