from __future__ import annotations

import logging
import re
from typing import Any, Callable
from urllib.parse import urlparse

from job_scraper.ats_extra import EXTRA_FETCHERS, extra_detect
from job_scraper.http import Http
from job_scraper.models import Job
from job_scraper.normalize import format_posted_date, html_to_text, join_location, looks_usa

logger = logging.getLogger(__name__)

Fetcher = Callable[[Http, str, str | None], list[Job]]

WORKDAY_URL = re.compile(
    r"https?://(?P<tenant>[^.]+)\.(?P<shard>wd\d+)\.myworkdayjobs\.com"
    r"(?:/(?P<lang>[a-z]{2}-[A-Z]{2}))?/(?P<site>[^/?#]+)",
    re.IGNORECASE,
)


def fetch_greenhouse(http: Http, slug: str, company: str | None = None) -> list[Job]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    response = http.get(url)
    if response.status_code == 404:
        logger.warning("Greenhouse board not found: %s", slug)
        return []
    response.raise_for_status()
    payload = response.json()
    jobs: list[Job] = []
    for item in payload.get("jobs") or []:
        loc = ((item.get("location") or {}).get("name")) or ""
        jobs.append(
            Job(
                title=(item.get("title") or "").strip(),
                company=item.get("company_name") or company or slug,
                source="greenhouse",
                url=item.get("absolute_url") or "",
                location=loc,
                department=_first_name(item.get("departments")),
                date_posted=format_posted_date(item.get("updated_at") or item.get("first_published")),
                description=html_to_text(item.get("content")),
                apply_url=item.get("absolute_url") or "",
                company_slug=slug,
            )
        )
    return jobs


def fetch_lever(http: Http, slug: str, company: str | None = None) -> list[Job]:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    response = http.get(url)
    if response.status_code == 404:
        logger.warning("Lever board not found: %s", slug)
        return []
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        return []
    jobs: list[Job] = []
    for item in payload:
        cats = item.get("categories") or {}
        locations = cats.get("allLocations") or [cats.get("location")]
        location = ", ".join(x for x in locations if x)
        created = item.get("createdAt")
        date_posted = format_posted_date(created)
        workplace = (item.get("workplaceType") or "").lower()
        jobs.append(
            Job(
                title=(item.get("text") or "").strip(),
                company=company or slug,
                source="lever",
                url=item.get("hostedUrl") or item.get("applyUrl") or "",
                location=location,
                is_remote=workplace == "remote" or "remote" in location.lower(),
                job_type=cats.get("commitment") or "",
                department=cats.get("department") or "",
                date_posted=date_posted,
                description=html_to_text(item.get("descriptionPlain") or item.get("description")),
                apply_url=item.get("applyUrl") or item.get("hostedUrl") or "",
                company_slug=slug,
            )
        )
    return jobs


def fetch_ashby(http: Http, slug: str, company: str | None = None) -> list[Job]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
    response = http.get(url)
    if response.status_code == 404:
        logger.warning("Ashby board not found: %s", slug)
        return []
    response.raise_for_status()
    payload = response.json() or {}
    jobs: list[Job] = []
    for item in payload.get("jobs") or []:
        extras = [loc.get("location") for loc in item.get("secondaryLocations") or [] if loc]
        location = join_location(item.get("location"), *extras)
        comp = item.get("compensation") or {}
        salary = ""
        if isinstance(comp, dict):
            salary = comp.get("compensationTierSummary") or comp.get("summary") or ""
        elif isinstance(comp, str):
            salary = comp
        jobs.append(
            Job(
                title=(item.get("title") or "").strip(),
                company=company or slug,
                source="ashby",
                url=item.get("jobUrl") or item.get("applyUrl") or "",
                location=location,
                is_remote=bool(item.get("isRemote")) or (item.get("workplaceType") or "").lower() == "remote",
                job_type=item.get("employmentType") or "",
                department=item.get("department") or item.get("team") or "",
                date_posted=format_posted_date(item.get("publishedAt")),
                description=html_to_text(item.get("descriptionHtml") or item.get("descriptionPlain")),
                salary=str(salary),
                apply_url=item.get("applyUrl") or item.get("jobUrl") or "",
                company_slug=slug,
            )
        )
    return jobs


def fetch_workable(http: Http, slug: str, company: str | None = None) -> list[Job]:
    url = f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true"
    response = http.get(url)
    if response.status_code == 404:
        logger.warning("Workable board not found: %s", slug)
        return []
    response.raise_for_status()
    payload = response.json() or {}
    company_name = payload.get("name") or company or slug
    jobs: list[Job] = []
    for item in payload.get("jobs") or []:
        location = join_location(item.get("city"), item.get("state"), item.get("country"))
        jobs.append(
            Job(
                title=(item.get("title") or "").strip(),
                company=company_name,
                source="workable",
                url=item.get("url") or item.get("application_url") or "",
                location=location,
                is_remote=bool(item.get("telecommuting")),
                job_type=item.get("employment_type") or "",
                department=item.get("department") or "",
                date_posted=format_posted_date(item.get("published_on")),
                description=html_to_text(item.get("description")),
                apply_url=item.get("application_url") or item.get("url") or "",
                company_slug=slug,
            )
        )
    return jobs


def fetch_smartrecruiters(http: Http, slug: str, company: str | None = None) -> list[Job]:
    jobs: list[Job] = []
    offset = 0
    limit = 100
    while True:
        url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
        response = http.get(url, params={"limit": limit, "offset": offset})
        if response.status_code == 404:
            logger.warning("SmartRecruiters board not found: %s", slug)
            return []
        response.raise_for_status()
        payload = response.json() or {}
        batch = payload.get("content") or []
        for item in batch:
            loc = item.get("location") or {}
            location = loc.get("fullLocation") or join_location(
                loc.get("city"), loc.get("region"), loc.get("country")
            )
            dept = item.get("department") or {}
            emp = item.get("typeOfEmployment") or {}
            company_obj = item.get("company") or {}
            posting_id = str(item.get("id") or "")
            detail_url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{posting_id}"
            description = ""
            if posting_id:
                try:
                    detail = http.get(detail_url)
                    if detail.status_code == 200:
                        body = detail.json() or {}
                        description = html_to_text(
                            body.get("jobAd", {}).get("sections", {}).get("jobDescription", {}).get("text")
                            or body.get("jobAd", {}).get("text")
                            or ""
                        )
                except Exception:
                    logger.debug("SmartRecruiters detail skipped for %s", posting_id)
            jobs.append(
                Job(
                    title=(item.get("name") or "").strip(),
                    company=company_obj.get("name") or company or slug,
                    source="smartrecruiters",
                    url=item.get("ref") or f"https://jobs.smartrecruiters.com/{slug}/{posting_id}",
                    location=location,
                    is_remote=bool(loc.get("remote")),
                    job_type=emp.get("label") or "",
                    department=dept.get("label") or "",
                    date_posted=format_posted_date(item.get("releasedDate")),
                    description=description,
                    apply_url=item.get("ref") or "",
                    company_slug=slug,
                )
            )
        total = int(payload.get("totalFound") or 0)
        offset += len(batch)
        if not batch or offset >= total:
            break
    return jobs


def fetch_recruitee(http: Http, slug: str, company: str | None = None) -> list[Job]:
    url = f"https://{slug}.recruitee.com/api/offers/"
    response = http.get(url)
    if response.status_code == 404:
        logger.warning("Recruitee board not found: %s", slug)
        return []
    response.raise_for_status()
    payload = response.json() or {}
    jobs: list[Job] = []
    for item in payload.get("offers") or []:
        locations = item.get("locations") or []
        loc_names = [loc.get("city") or loc.get("country") for loc in locations]
        jobs.append(
            Job(
                title=(item.get("title") or "").strip(),
                company=company or slug,
                source="recruitee",
                url=item.get("careers_url") or "",
                location=join_location(*loc_names),
                is_remote=bool(item.get("remote")),
                job_type=item.get("employment_type_code") or "",
                department=item.get("department") or "",
                date_posted=format_posted_date(item.get("published_at")),
                description=html_to_text(item.get("description")),
                apply_url=item.get("careers_url") or "",
                company_slug=slug,
            )
        )
    return jobs


def fetch_workday(
    http: Http,
    board_url: str,
    company: str | None = None,
    max_jobs: int | None = None,
    search_text: str = "",
) -> list[Job]:
    parsed = parse_workday_url(board_url)
    if not parsed:
        logger.warning("Could not parse Workday URL: %s", board_url)
        return []
    tenant, shard, site = parsed
    origin = f"https://{tenant}.{shard}.myworkdayjobs.com"
    list_url = f"{origin}/wday/cxs/{tenant}/{site}/jobs"
    jobs: list[Job] = []
    offset = 0
    limit = 20
    total: int | None = None
    while True:
        response = http.post(
            list_url,
            json={"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": search_text or ""},
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Referer": f"{origin}/{site}",
            },
        )
        if response.status_code in {404, 400}:
            logger.warning("Workday board not found: %s", board_url)
            return []
        response.raise_for_status()
        payload = response.json() or {}
        if total is None:
            total = int(payload.get("total") or 0)
        batch = payload.get("jobPostings") or []
        for item in batch:
            path = item.get("externalPath") or ""
            url = f"https://{tenant}.{shard}.myworkdayjobs.com/{site}{path}"
            location = item.get("locationsText") or ""
            jobs.append(
                Job(
                    title=(item.get("title") or "").strip(),
                    company=company or tenant,
                    source="workday",
                    url=url,
                    location=location,
                    is_remote="remote" in location.lower(),
                    date_posted=format_posted_date(item.get("postedOn")),
                    apply_url=url,
                    company_slug=tenant,
                    extra={"site": site},
                )
            )
            if max_jobs and len(jobs) >= max_jobs:
                return jobs
        offset += len(batch)
        if not batch or (total is not None and offset >= total):
            break
        if offset > 5000:
            break
    return jobs


FETCHERS: dict[str, Fetcher] = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "workable": fetch_workable,
    "smartrecruiters": fetch_smartrecruiters,
    "recruitee": fetch_recruitee,
    "workday": fetch_workday,
    **EXTRA_FETCHERS,
}


def parse_workday_url(url: str) -> tuple[str, str, str] | None:
    match = WORKDAY_URL.search(url or "")
    if not match:
        return None
    return match.group("tenant"), match.group("shard").lower(), match.group("site")


def detect_from_url(url: str) -> tuple[str, str] | None:
    raw = (url or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.netloc or "").lower()
    path = parsed.path.strip("/")
    slug = path.split("/")[0] if path else ""

    if "greenhouse.io" in host:
        return "greenhouse", slug
    if host.endswith("lever.co") or host == "jobs.lever.co":
        return "lever", slug
    if "ashbyhq.com" in host:
        return "ashby", slug
    if "workable.com" in host:
        return "workable", slug
    if "smartrecruiters.com" in host:
        return "smartrecruiters", slug
    if host.endswith("recruitee.com"):
        return "recruitee", host.split(".")[0]
    if "myworkdayjobs.com" in host:
        return "workday", raw
    return extra_detect(host, path, raw)


def fetch_board(
    http: Http,
    ats: str,
    slug: str,
    company: str | None = None,
    max_jobs: int | None = None,
    query: str | None = None,
) -> list[Job]:
    fetcher = FETCHERS.get(ats.lower())
    if not fetcher:
        raise ValueError(f"Unsupported ATS: {ats}")
    logger.info("Fetching %s board %s", ats, slug)
    if ats.lower() == "workday":
        jobs = fetch_workday(
            http,
            slug,
            company,
            max_jobs=max_jobs,
            search_text=query or "",
        )
    else:
        jobs = fetcher(http, slug, company)
    return jobs


def fetch_all(
    http: Http,
    ats_config: dict[str, Any],
    usa_only: bool = True,
    max_jobs_per_board: int | None = 400,
    query: str | None = None,
) -> list[Job]:
    jobs: list[Job] = []
    for ats, entries in (ats_config or {}).items():
        key = (ats or "").lower()
        if key == "ycombinator":
            if not entries:
                continue
            jobs.extend(
                _collect_board(
                    http,
                    "ycombinator",
                    "all",
                    None,
                    usa_only=usa_only,
                    max_jobs_per_board=max_jobs_per_board,
                    query=query,
                )
            )
            continue
        for entry in entries or []:
            slug, company = _entry(ats, entry)
            if not slug:
                continue
            jobs.extend(
                _collect_board(
                    http,
                    ats,
                    slug,
                    company,
                    usa_only=usa_only,
                    max_jobs_per_board=max_jobs_per_board,
                    query=query,
                )
            )
    return jobs


def _collect_board(
    http: Http,
    ats: str,
    slug: str,
    company: str | None,
    *,
    usa_only: bool,
    max_jobs_per_board: int | None,
    query: str | None,
) -> list[Job]:
    try:
        found = fetch_board(
            http, ats, slug, company, max_jobs=max_jobs_per_board, query=query
        )
    except Exception:
        logger.exception("Failed fetching %s:%s", ats, slug)
        return []
    if query:
        found = [job for job in found if _title_matches(job.title, query)]
    if usa_only:
        found = [job for job in found if looks_usa(job.location, job.is_remote)]
    if max_jobs_per_board:
        found = found[: int(max_jobs_per_board)]
    return found


def _entry(ats: str, entry: Any) -> tuple[str, str | None]:
    if isinstance(entry, str):
        detected = detect_from_url(entry)
        if detected:
            return detected[1] if detected[0] == ats or ats == "workday" else entry, None
        return entry, None
    if isinstance(entry, dict):
        url = entry.get("url") or ""
        name = entry.get("name") or entry.get("company")
        slug = entry.get("slug") or entry.get("id")
        if url:
            detected = detect_from_url(url)
            if detected:
                return detected[1], name
            if ats == "workday":
                return url, name
        return str(slug or ""), name
    return "", None


def _first_name(items: Any) -> str:
    if not items:
        return ""
    first = items[0] if isinstance(items, list) else items
    if isinstance(first, dict):
        return str(first.get("name") or "")
    return str(first)


def _title_matches(title: str, query: str) -> bool:
    q = (query or "").strip().lower()
    if not q:
        return True
    hay = (title or "").lower()
    if q in hay:
        return True
    tokens = [tok for tok in re.findall(r"[a-z0-9]+", q) if tok not in {"and", "or", "the", "a"}]
    return bool(tokens) and all(tok in hay for tok in tokens)
