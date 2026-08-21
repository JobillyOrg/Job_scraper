from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from job_scraper.ats import count_ats_tasks, fetch_all
from job_scraper.boards import scrape_boards
from job_scraper.db import upsert_jobs
from job_scraper.freehire import fetch_freehire
from job_scraper.http import Http
from job_scraper.models import Job
from job_scraper.parallel import gather
from job_scraper.progress import Progress

logger = logging.getLogger(__name__)


def run_scrape(config: dict, progress: Progress | None = None) -> list[Job]:
    boards = list(config.get("boards") or [])
    jobspy_boards = [name for name in boards if name != "freehire"]
    ats = config.get("ats") or {}
    want_freehire = "freehire" in boards
    query = config["query"]
    location = config.get("location") or "United States"
    usa_only = bool(config.get("usa_only", True))
    results_wanted = int(config.get("results_wanted") or 100)
    total = len(jobspy_boards) + (1 if want_freehire else 0) + count_ats_tasks(ats)
    if progress:
        progress.set_total(total, "Fetching sources…")

    def _boards() -> list[Job]:
        if not jobspy_boards:
            return []
        try:
            return scrape_boards(
                query=query,
                location=location,
                site_name=jobspy_boards,
                country_indeed=config.get("country_indeed") or "USA",
                results_wanted=results_wanted,
                hours_old=config.get("hours_old"),
                linkedin_fetch_description=bool(config.get("linkedin_fetch_description")),
                proxies=config.get("proxies"),
                progress=progress,
            )
        except Exception:
            logger.exception("Job board scrape failed (LinkedIn/Indeed often block). Continuing with other sources.")
            return []

    def _freehire() -> list[Job]:
        if not want_freehire:
            return []
        try:
            with Http() as http:
                jobs = fetch_freehire(
                    http,
                    query=query,
                    location=location,
                    results_wanted=results_wanted,
                    hours_old=config.get("hours_old"),
                    usa_only=usa_only,
                )
            if progress:
                progress.step("Freehire")
            return jobs
        except Exception:
            logger.exception("Freehire search failed")
            if progress:
                progress.step("Freehire")
            return []

    def _ats() -> list[Job]:
        if not ats:
            return []
        with Http() as http:
            return fetch_all(
                http,
                ats,
                usa_only=usa_only,
                max_jobs_per_board=config.get("max_jobs_per_board"),
                query=query,
                progress=progress,
            )

    tasks = []
    if jobspy_boards:
        tasks.append(_boards)
    if want_freehire:
        tasks.append(_freehire)
    if ats:
        tasks.append(_ats)
    return _dedupe(gather(tasks, max_workers=3))


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
