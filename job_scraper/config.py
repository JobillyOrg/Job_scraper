from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULTS: dict[str, Any] = {
    "query": "software engineer",
    "location": "United States",
    "country_indeed": "USA",
    "results_wanted": 100,
    "hours_old": 168,
    "linkedin_fetch_description": False,
    "usa_only": True,
    "boards": ["indeed", "zip_recruiter", "linkedin"],
    "ats": {},
    "output": "output/jobs.csv",
    "proxies": None,
    "max_jobs_per_board": 400,
}


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    data: dict[str, Any] = {}
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"Config {config_path} must be a YAML mapping")
        data = loaded
    merged = {**DEFAULTS, **data}
    merged["ats"] = merged.get("ats") or {}
    merged["boards"] = merged.get("boards") or []
    return merged
