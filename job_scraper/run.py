from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from job_scraper.ats import fetch_all
from job_scraper.boards import scrape_boards
from job_scraper.db import upsert_jobs
from job_scraper.http import Http
from job_scraper.models import Job

logger = logging.getLogger(__name__)


def run_scrape(config: dict) -> list[Job]:
    jobs: list[Job] = []
    boards = config.get("boards") or []
    if boards:
        try:
            jobs.extend(
                scrape_boards(
                    query=config["query"],
                    location=config.get("location") or "United States",
                    site_name=boards,
                    country_indeed=config.get("country_indeed") or "USA",
                    results_wanted=int(config.get("results_wanted") or 100),
                    hours_old=config.get("hours_old"),
                    linkedin_fetch_description=bool(config.get("linkedin_fetch_description")),
                    proxies=config.get("proxies"),
                )
            )
        except Exception:
            logger.exception("Job board scrape failed (LinkedIn/Indeed often block). Continuing with ATS.")

    ats = config.get("ats") or {}
    if ats:
        with Http() as http:
            jobs.extend(fetch_all(
                http,
                ats,
                usa_only=bool(config.get("usa_only", True)),
                max_jobs_per_board=config.get("max_jobs_per_board"),
                query=config.get("query"),
            ))

    return _dedupe(jobs)


def save_jobs(jobs: list[Job], output: str | Path) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [job.to_row() for job in jobs]
    frame = pd.DataFrame(rows)
    preferred = [
        "source",
        "company",
        "title",
        "location",
        "is_remote",
        "job_type",
        "department",
        "date_posted",
        "salary",
        "url",
        "apply_url",
        "description",
    ]
    cols = [c for c in preferred if c in frame.columns] + [
        c for c in frame.columns if c not in preferred
    ]
    if not frame.empty:
        frame = frame[cols]
    suffix = path.suffix.lower()
    if suffix == ".json":
        frame.to_json(path, orient="records", indent=2)
    elif suffix in {".xlsx", ".xls"}:
        frame.to_excel(path, index=False)
    else:
        frame.to_csv(path, index=False)
    return path


def persist_jobs(jobs: list[Job], output: str | Path, query: str = "") -> dict[str, int]:
    save_jobs(jobs, output)
    return upsert_jobs(jobs, query=query)


def _dedupe(jobs: list[Job]) -> list[Job]:
    seen: set[str] = set()
    unique: list[Job] = []
    for job in jobs:
        key = (job.url or f"{job.source}|{job.company}|{job.title}").strip().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique
