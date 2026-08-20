from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from job_scraper.config import load_config
from job_scraper.run import persist_jobs, run_scrape

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scrape USA jobs from LinkedIn, Indeed, ZipRecruiter, and ATS boards."
    )
    parser.add_argument("--config", default="config.yaml", help="YAML config path")
    parser.add_argument("--query", help="Override search term for job boards")
    parser.add_argument("--location", help="Override location (default: United States)")
    parser.add_argument("--boards-only", action="store_true", help="Skip ATS career pages")
    parser.add_argument("--ats-only", action="store_true", help="Skip LinkedIn/Indeed/ZipRecruiter")
    parser.add_argument("--no-linkedin", action="store_true", help="Drop LinkedIn (less blocking)")
    parser.add_argument("--out", help="CSV/JSON/XLSX output path")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    if not config_path.exists() and args.config == "config.yaml":
        print("No config.yaml found; using built-in defaults.", file=sys.stderr)
    config = load_config(config_path)

    if args.query:
        config["query"] = args.query
    if args.location:
        config["location"] = args.location
    if args.out:
        config["output"] = args.out
    if args.boards_only:
        config["ats"] = {}
    if args.ats_only:
        config["boards"] = []
    if args.no_linkedin:
        config["boards"] = [b for b in config["boards"] if b != "linkedin"]

    jobs = run_scrape(config)
    stats = persist_jobs(jobs, config["output"], query=str(config.get("query") or ""))

    counts: dict[str, int] = {}
    for job in jobs:
        counts[job.source] = counts.get(job.source, 0) + 1

    print(f"Wrote {len(jobs)} jobs to {config['output']}")
    print(f"Database: {stats['inserted']} new, {stats['updated']} updated")
    for source, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {source}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
