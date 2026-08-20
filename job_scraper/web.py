from __future__ import annotations

import logging
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from job_scraper.config import load_config
from job_scraper.db import import_csv_if_empty, list_jobs
from job_scraper.group import group_jobs
from job_scraper.models import Job
from job_scraper.run import persist_jobs, run_scrape

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
CONFIG_PATH = ROOT / "config.yaml"

BOARD_OPTIONS = ["indeed", "linkedin", "zip_recruiter"]
ATS_OPTIONS = [
    "greenhouse",
    "ashby",
    "lever",
    "workable",
    "workday",
    "smartrecruiters",
    "recruitee",
    "bamboohr",
    "personio",
    "breezy",
    "teamtailor",
    "pinpoint",
    "jazzhr",
    "manatal",
    "polymer",
    "icims",
    "paylocity",
    "paycom",
    "successfactors",
    "ycombinator",
]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    imported = import_csv_if_empty(ROOT / "output" / "jobs.csv")
    if imported:
        logging.info("Imported %s jobs from CSV into the database", imported)
    yield


app = FastAPI(title="Job scraper", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")

_lock = threading.Lock()
_runs: dict[str, dict[str, Any]] = {}


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    location: str = "United States"
    boards: list[str] = Field(default_factory=list)
    ats: list[str] = Field(default_factory=list)
    usa_only: bool = True
    results_wanted: int = Field(default=100, ge=5, le=200)


def _base_config() -> dict[str, Any]:
    return load_config(CONFIG_PATH)


def _public_jobs(jobs: list[Job]) -> list[dict[str, Any]]:
    return group_jobs([job.to_public() for job in jobs])


def _counts(jobs: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for job in jobs:
        source = job.get("source") or "unknown"
        counts[source] = counts.get(source, 0) + 1
    return counts


def _execute_search(run_id: str, request: SearchRequest) -> None:
    config = _base_config()
    config["query"] = request.query.strip()
    config["location"] = request.location.strip() or "United States"
    config["usa_only"] = request.usa_only
    config["results_wanted"] = request.results_wanted
    config["boards"] = [b for b in request.boards if b in BOARD_OPTIONS]
    config["linkedin_fetch_description"] = "linkedin" in config["boards"]
    selected_ats = {name for name in request.ats if name in ATS_OPTIONS}
    config["ats"] = {
        name: companies
        for name, companies in (config.get("ats") or {}).items()
        if name in selected_ats
    }
    try:
        jobs = run_scrape(config)
        stats = persist_jobs(jobs, ROOT / "output" / "jobs.csv", query=request.query)
        payload = _public_jobs(jobs)
        with _lock:
            _runs[run_id] = {
                "status": "done",
                "jobs": payload,
                "counts": _counts(payload),
                "saved": stats,
                "error": None,
            }
    except Exception as exc:
        logging.exception("Search failed")
        with _lock:
            _runs[run_id] = {
                "status": "error",
                "jobs": [],
                "counts": {},
                "error": str(exc),
            }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/defaults")
def defaults() -> dict[str, Any]:
    config = _base_config()
    ats_config = config.get("ats") or {}
    return {
        "query": config.get("query") or "software engineer",
        "location": config.get("location") or "United States",
        "usa_only": bool(config.get("usa_only", True)),
        "results_wanted": int(config.get("results_wanted") or 25),
        "boards": [b for b in (config.get("boards") or []) if b in BOARD_OPTIONS],
        "ats": [name for name in ATS_OPTIONS if ats_config.get(name)],
        "board_options": BOARD_OPTIONS,
        "ats_options": ATS_OPTIONS,
    }


@app.get("/api/jobs")
def saved_jobs() -> dict[str, Any]:
    jobs = group_jobs(list_jobs())
    return {"jobs": jobs, "counts": _counts(jobs)}


@app.post("/api/search")
def start_search(request: SearchRequest) -> dict[str, str]:
    if not request.boards and not request.ats:
        raise HTTPException(status_code=400, detail="Select at least one source.")
    with _lock:
        if any(run.get("status") == "running" for run in _runs.values()):
            raise HTTPException(status_code=409, detail="A search is already running.")
        run_id = str(uuid.uuid4())
        _runs[run_id] = {"status": "running", "jobs": [], "counts": {}, "error": None}
    thread = threading.Thread(target=_execute_search, args=(run_id, request), daemon=True)
    thread.start()
    return {"id": run_id}


@app.get("/api/search/{run_id}")
def search_status(run_id: str) -> dict[str, Any]:
    with _lock:
        run = _runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Search not found.")
    return run


def main() -> None:
    import uvicorn

    uvicorn.run("job_scraper.web:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
