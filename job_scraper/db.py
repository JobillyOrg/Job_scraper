from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from job_scraper.models import Job
from job_scraper.normalize import format_posted_date

logger = logging.getLogger(__name__)

DEFAULT_DB = Path(__file__).resolve().parent.parent / "output" / "jobs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key TEXT NOT NULL UNIQUE,
    url TEXT,
    apply_url TEXT,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    source TEXT NOT NULL,
    location TEXT,
    is_remote INTEGER,
    job_type TEXT,
    department TEXT,
    date_posted TEXT,
    salary TEXT,
    description TEXT,
    company_slug TEXT,
    query TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);
CREATE INDEX IF NOT EXISTS idx_jobs_posted ON jobs(date_posted);
"""


def job_key(job: Job) -> str:
    url = (job.url or job.apply_url or "").strip().lower()
    if url:
        return url
    return "|".join(
        part.strip().lower()
        for part in (job.source, job.company, job.title, job.location)
        if part
    )


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    db_path = Path(path) if path else DEFAULT_DB
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def upsert_jobs(
    jobs: Iterable[Job],
    query: str = "",
    path: str | Path | None = None,
) -> dict[str, int]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    inserted = 0
    updated = 0
    with connect(path) as conn:
        for job in jobs:
            key = job_key(job)
            if not key:
                continue
            remote = None if job.is_remote is None else int(bool(job.is_remote))
            existing = conn.execute(
                "SELECT id FROM jobs WHERE job_key = ?", (key,)
            ).fetchone()
            conn.execute(
                """
                INSERT INTO jobs (
                    job_key, url, apply_url, title, company, source, location,
                    is_remote, job_type, department, date_posted, salary,
                    description, company_slug, query, first_seen, last_seen
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_key) DO UPDATE SET
                    url = excluded.url,
                    apply_url = excluded.apply_url,
                    title = excluded.title,
                    company = excluded.company,
                    source = excluded.source,
                    location = excluded.location,
                    is_remote = excluded.is_remote,
                    job_type = excluded.job_type,
                    department = excluded.department,
                    date_posted = excluded.date_posted,
                    salary = excluded.salary,
                    description = CASE
                        WHEN excluded.description != '' THEN excluded.description
                        ELSE jobs.description
                    END,
                    company_slug = excluded.company_slug,
                    query = excluded.query,
                    last_seen = excluded.last_seen
                """,
                (
                    key,
                    job.url or job.apply_url,
                    job.apply_url or job.url,
                    job.title or "",
                    job.company or "",
                    job.source or "",
                    job.location or "",
                    remote,
                    job.job_type or "",
                    job.department or "",
                    format_posted_date(job.date_posted) or (job.date_posted or ""),
                    job.salary or "",
                    (job.description or "").strip(),
                    job.company_slug or "",
                    query,
                    now,
                    now,
                ),
            )
            if existing:
                updated += 1
            else:
                inserted += 1
        conn.commit()
    logger.info("Database saved %s new, %s updated", inserted, updated)
    return {"inserted": inserted, "updated": updated, "total": inserted + updated}


def list_jobs(path: str | Path | None = None, limit: int = 2000) -> list[dict[str, Any]]:
    with connect(path) as conn:
        rows = conn.execute(
            """
            SELECT title, company, source, url, location, is_remote, job_type,
                   department, date_posted, salary, apply_url, description
            FROM jobs
            ORDER BY last_seen DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    jobs: list[dict[str, Any]] = []
    for row in rows:
        remote = row["is_remote"]
        jobs.append(
            {
                "title": row["title"] or "",
                "company": row["company"] or "",
                "source": row["source"] or "",
                "url": row["url"] or row["apply_url"] or "",
                "location": row["location"] or "",
                "is_remote": None if remote is None else bool(remote),
                "job_type": row["job_type"] or "",
                "department": row["department"] or "",
                "date_posted": format_posted_date(row["date_posted"]) or (row["date_posted"] or ""),
                "salary": row["salary"] or "",
                "apply_url": row["apply_url"] or row["url"] or "",
                "description": row["description"] or "",
            }
        )
    return jobs


def counts(path: str | Path | None = None) -> dict[str, int]:
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT source, COUNT(*) AS n FROM jobs GROUP BY source ORDER BY n DESC"
        ).fetchall()
    return {str(row["source"]): int(row["n"]) for row in rows}


def import_csv_if_empty(csv_path: str | Path, db_path: str | Path | None = None) -> int:
    csv_file = Path(csv_path)
    if not csv_file.exists():
        return 0
    with connect(db_path) as conn:
        existing = conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()
        if existing and int(existing["n"]) > 0:
            return 0
    try:
        import pandas as pd

        frame = pd.read_csv(csv_file).fillna("")
        jobs = [Job.from_row(row) for row in frame.to_dict(orient="records")]
    except Exception:
        logger.exception("Could not import CSV into the database")
        return 0
    jobs = [job for job in jobs if job.title]
    if not jobs:
        return 0
    result = upsert_jobs(jobs, query="imported", path=db_path)
    return int(result["inserted"])
