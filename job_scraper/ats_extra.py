from __future__ import annotations

import html
import json
import logging
import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urljoin, urlparse

from job_scraper.http import Http
from job_scraper.models import Job
from job_scraper.normalize import format_posted_date, html_to_text, join_location, title_matches
from job_scraper.parallel import map_pool

logger = logging.getLogger(__name__)


def _not_found(response: Any) -> bool:
    if response.status_code in {404, 410}:
        return True
    if response.status_code in {301, 302, 303, 307, 308}:
        location = (response.headers.get("location") or "").lower()
        if any(
            host in location
            for host in (
                "bamboohr.com",
                "personio.com",
                "personio.de",
                "jazzhr.com",
                "www.paycom",
                "breezy.hr",
            )
        ):
            return True
    return False


def fetch_bamboohr(
    http: Http,
    slug: str,
    company: str | None = None,
    query: str | None = None,
) -> list[Job]:
    url = f"https://{slug}.bamboohr.com/careers/list"
    response = http.get(url, follow_redirects=False)
    if _not_found(response):
        logger.warning("BambooHR board not found: %s", slug)
        return []
    response.raise_for_status()
    payload = response.json() or {}
    listings = list(payload.get("result") or [])
    if query:
        listings = [item for item in listings if title_matches(item.get("jobOpeningName") or "", query)]

    def _one(item: dict[str, Any]) -> Job:
        job_id = str(item.get("id") or "")
        loc = item.get("location") or {}
        ats_loc = item.get("atsLocation") or {}
        location = join_location(
            loc.get("city") or ats_loc.get("city"),
            loc.get("state") or ats_loc.get("state") or ats_loc.get("province"),
            ats_loc.get("country"),
        )
        description = ""
        if job_id:
            try:
                detail = http.get(f"https://{slug}.bamboohr.com/careers/{job_id}/detail")
                if detail.status_code == 200:
                    body = detail.json() or {}
                    result = body.get("result") or body
                    description = html_to_text(
                        result.get("description") or result.get("jobOpening") or ""
                    )
                    if not location:
                        dloc = result.get("location") or {}
                        location = join_location(dloc.get("city"), dloc.get("state"), dloc.get("country"))
            except Exception:
                logger.debug("BambooHR detail skipped for %s", job_id)
        return Job(
            title=(item.get("jobOpeningName") or "").strip(),
            company=company or slug,
            source="bamboohr",
            url=f"https://{slug}.bamboohr.com/careers/{job_id}" if job_id else "",
            location=location,
            is_remote=bool(item.get("isRemote")) or "remote" in location.lower(),
            job_type=item.get("employmentStatusLabel") or item.get("employmentType") or "",
            department=item.get("departmentLabel") or "",
            description=description,
            apply_url=f"https://{slug}.bamboohr.com/careers/{job_id}" if job_id else "",
            company_slug=slug,
        )

    return map_pool(_one, listings, max_workers=8)


def fetch_personio(http: Http, slug: str, company: str | None = None) -> list[Job]:
    jobs: list[Job] = []
    for host in (f"https://{slug}.jobs.personio.com/xml", f"https://{slug}.jobs.personio.de/xml"):
        response = http.get(
            host,
            headers={"Accept": "application/xml, text/xml, */*"},
            follow_redirects=False,
        )
        if _not_found(response) or response.status_code >= 400:
            continue
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError:
            continue
        for pos in root.findall(".//position"):
            title = (pos.findtext("name") or "").strip()
            offices = [pos.findtext("office") or ""]
            for extra in pos.findall("./additionalOffices/office"):
                if extra.text:
                    offices.append(extra.text)
            descriptions = [
                html_to_text(block.findtext("value"))
                for block in pos.findall("./jobDescriptions/jobDescription")
            ]
            job_id = (pos.findtext("id") or "").strip()
            apply = f"https://{slug}.jobs.personio.com/job/{job_id}" if job_id else host.replace("/xml", "")
            jobs.append(
                Job(
                    title=title,
                    company=pos.findtext("subcompany") or company or slug,
                    source="personio",
                    url=apply,
                    location=join_location(*offices),
                    job_type=pos.findtext("employmentType") or "",
                    department=pos.findtext("department") or pos.findtext("recruitingCategory") or "",
                    date_posted=format_posted_date(pos.findtext("createdAt")),
                    description="\n\n".join(part for part in descriptions if part),
                    apply_url=apply,
                    company_slug=slug,
                )
            )
        if jobs:
            return jobs
    if not jobs:
        logger.warning("Personio board not found: %s", slug)
    return jobs


def fetch_breezy(http: Http, slug: str, company: str | None = None) -> list[Job]:
    url = f"https://{slug}.breezy.hr/json"
    response = http.get(url, params={"verbose": "true"}, follow_redirects=False)
    if _not_found(response):
        logger.warning("Breezy board not found: %s", slug)
        return []
    response.raise_for_status()
    try:
        payload = response.json()
    except Exception:
        logger.warning("Breezy board did not return JSON: %s", slug)
        return []
    items = payload if isinstance(payload, list) else payload.get("positions") or payload.get("jobs") or []
    jobs: list[Job] = []
    for item in items:
        loc = item.get("location") or {}
        if isinstance(loc, dict):
            location = loc.get("name") or join_location(loc.get("city"), loc.get("country"))
        else:
            location = str(loc or "")
        apply = item.get("url") or item.get("application_url") or ""
        jobs.append(
            Job(
                title=(item.get("name") or item.get("title") or "").strip(),
                company=company or slug,
                source="breezy",
                url=apply,
                location=location,
                is_remote=bool(item.get("remote")) or "remote" in location.lower(),
                job_type=item.get("type") or item.get("category") or "",
                department=item.get("department") or "",
                date_posted=format_posted_date(item.get("published_date") or item.get("created_at")),
                description=html_to_text(item.get("description") or item.get("cleaned_description")),
                apply_url=apply,
                company_slug=slug,
            )
        )
    return jobs


def fetch_teamtailor(http: Http, slug: str, company: str | None = None) -> list[Job]:
    if slug.startswith("http"):
        parsed = urlparse(slug)
        url = f"{parsed.scheme}://{parsed.netloc}/jobs.json"
        display = company or parsed.netloc
    else:
        url = f"https://{slug}.teamtailor.com/jobs.json"
        display = company or slug
    response = http.get(url)
    if response.status_code == 404:
        logger.warning("Teamtailor board not found: %s", slug)
        return []
    response.raise_for_status()
    payload = response.json() or {}
    jobs: list[Job] = []
    for item in payload.get("items") or []:
        posting = item.get("job_posting") or item.get("jobPosting") or {}
        loc_obj = posting.get("jobLocation") or {}
        address = loc_obj.get("address") or loc_obj if isinstance(loc_obj, dict) else {}
        if isinstance(address, dict):
            location = join_location(
                address.get("addressLocality"),
                address.get("addressRegion"),
                address.get("addressCountry"),
            )
        else:
            location = str(address or "")
        org = posting.get("hiringOrganization") or {}
        jobs.append(
            Job(
                title=(posting.get("title") or item.get("title") or "").strip(),
                company=(org.get("name") if isinstance(org, dict) else None) or display,
                source="teamtailor",
                url=item.get("url") or posting.get("url") or "",
                location=location,
                is_remote="remote" in location.lower() or (posting.get("jobLocationType") or "") == "TELECOMMUTE",
                date_posted=format_posted_date(posting.get("datePosted") or item.get("date_published")),
                description=html_to_text(item.get("content_html") or posting.get("description")),
                apply_url=item.get("url") or posting.get("url") or "",
                company_slug=slug,
            )
        )
    return jobs


def fetch_pinpoint(http: Http, slug: str, company: str | None = None) -> list[Job]:
    url = f"https://{slug}.pinpointhq.com/postings.json"
    response = http.get(url)
    if response.status_code == 404:
        logger.warning("Pinpoint board not found: %s", slug)
        return []
    response.raise_for_status()
    payload = response.json()
    items = payload if isinstance(payload, list) else payload.get("data") or payload.get("jobs") or []
    jobs: list[Job] = []
    for item in items:
        loc = item.get("location") or {}
        if isinstance(loc, dict):
            location = loc.get("name") or join_location(loc.get("city"), loc.get("country"))
        else:
            location = str(loc or item.get("location_name") or "")
        apply = item.get("url") or item.get("job_url") or ""
        jobs.append(
            Job(
                title=(item.get("title") or item.get("name") or "").strip(),
                company=item.get("company") or company or slug,
                source="pinpoint",
                url=apply,
                location=location,
                is_remote=bool(item.get("remote")) or "remote" in location.lower(),
                job_type=item.get("employment_type") or "",
                department=item.get("department") or "",
                date_posted=format_posted_date(item.get("published_on") or item.get("created_at")),
                description=html_to_text(item.get("description") or item.get("key_responsibilities")),
                salary=str(item.get("compensation_listing") or item.get("salary") or ""),
                apply_url=apply,
                company_slug=slug,
            )
        )
    return jobs


def fetch_jazzhr(http: Http, slug: str, company: str | None = None) -> list[Job]:
    url = f"https://{slug}.applytojob.com/apply"
    response = http.get(url, headers={"Accept": "text/html, */*"}, follow_redirects=True)
    if response.status_code == 404 or "applytojob.com" not in str(response.url):
        logger.warning("JazzHR board not found: %s", slug)
        return []
    html = response.text
    jobs: list[Job] = []
    pattern = re.compile(
        r'href="(/apply/[^"]+)"[^>]*>\s*(?:<[^>]+>)*\s*([^<]+)',
        re.IGNORECASE,
    )
    seen: set[str] = set()
    for href, title in pattern.findall(html):
        title = html_to_text(title)
        if not title or href in seen or "/apply/" not in href:
            continue
        if href.rstrip("/").endswith("/apply"):
            continue
        seen.add(href)
        apply = urljoin(str(response.url), href)
        jobs.append(
            Job(
                title=title.strip(),
                company=company or slug,
                source="jazzhr",
                url=apply,
                apply_url=apply,
                company_slug=slug,
            )
        )
    return jobs


def fetch_manatal(http: Http, slug: str, company: str | None = None) -> list[Job]:
    url = f"https://api.manatal.com/open/v3/career-page/{slug}/jobs/"
    jobs: list[Job] = []
    page = 1
    while True:
        response = http.get(url, params={"page": page, "page_size": 100})
        if response.status_code == 404:
            logger.warning("Manatal board not found: %s", slug)
            return []
        response.raise_for_status()
        payload = response.json() or {}
        batch = payload.get("results") or payload.get("jobs") or (payload if isinstance(payload, list) else [])
        if isinstance(payload, dict) and "results" not in payload and "jobs" not in payload:
            batch = payload.get("data") or []
        for item in batch:
            apply = item.get("career_page_url") or item.get("url") or f"https://www.careers-page.com/{slug}/job/{item.get('id', '')}"
            jobs.append(
                Job(
                    title=(item.get("position_name") or item.get("title") or "").strip(),
                    company=item.get("organization_name") or company or slug,
                    source="manatal",
                    url=apply,
                    location=join_location(item.get("city"), item.get("country")),
                    is_remote=bool(item.get("is_remote")),
                    job_type=item.get("contract_details") or "",
                    date_posted=format_posted_date(item.get("created_at") or item.get("published_at")),
                    description=html_to_text(item.get("description")),
                    apply_url=apply,
                    company_slug=slug,
                )
            )
        if not batch or (isinstance(payload, dict) and not payload.get("next")):
            break
        page += 1
        if page > 20:
            break
    return jobs


def fetch_polymer(http: Http, slug: str, company: str | None = None) -> list[Job]:
    url = f"https://api.polymer.co/v1/hire/organizations/{slug}/jobs"
    response = http.get(url)
    if response.status_code == 404:
        logger.warning("Polymer board not found: %s", slug)
        return []
    response.raise_for_status()
    payload = response.json() or {}
    items = payload.get("jobs") or payload.get("data") or payload.get("results") or []
    if isinstance(payload, list):
        items = payload
    jobs: list[Job] = []
    for item in items:
        apply = item.get("url") or item.get("apply_url") or f"https://jobs.polymer.co/{slug}/{item.get('id', '')}"
        loc = item.get("location") or {}
        location = loc if isinstance(loc, str) else join_location(loc.get("city"), loc.get("region"), loc.get("country"))
        jobs.append(
            Job(
                title=(item.get("title") or item.get("name") or "").strip(),
                company=item.get("organization_name") or company or slug,
                source="polymer",
                url=apply,
                location=location,
                is_remote=bool(item.get("remote") or item.get("is_remote")),
                date_posted=format_posted_date(item.get("published_at") or item.get("created_at")),
                description=html_to_text(item.get("description")),
                apply_url=apply,
                company_slug=slug,
            )
        )
    return jobs


def fetch_icims(http: Http, slug: str, company: str | None = None) -> list[Job]:
    if slug.startswith("http"):
        board = slug.split("?")[0].rstrip("/")
    else:
        board = f"https://careers-{slug}.icims.com/jobs/search"
    response = http.get(
        board,
        params={"ss": "1", "searchRelation": "and_all", "in_iframe": "1"},
        headers={"Accept": "text/html, application/json, */*"},
    )
    if response.status_code == 404:
        logger.warning("iCIMS board not found: %s", slug)
        return []
    jobs: list[Job] = []
    if "application/json" in (response.headers.get("content-type") or "") :
        payload = response.json()
        items = payload.get("jobs") or payload.get("items") or []
        for item in items:
            apply = item.get("url") or item.get("jobUrl") or ""
            jobs.append(
                Job(
                    title=(item.get("title") or item.get("jobTitle") or "").strip(),
                    company=company or slug,
                    source="icims",
                    url=apply,
                    location=item.get("location") or item.get("jobLocation") or "",
                    description=html_to_text(item.get("description")),
                    apply_url=apply,
                    company_slug=slug,
                )
            )
        return jobs
    html = response.text
    pattern = re.compile(r'href="([^"]+/jobs/\d+/[^"]*)"[^>]*>\s*([^<]+)', re.IGNORECASE)
    seen: set[str] = set()
    for href, title in pattern.findall(html):
        title = html_to_text(title).strip()
        if not title or href in seen:
            continue
        seen.add(href)
        apply = urljoin(str(response.url), href)
        jobs.append(
            Job(
                title=title,
                company=company or slug,
                source="icims",
                url=apply,
                apply_url=apply,
                company_slug=slug,
            )
        )
    return jobs


def fetch_paylocity(http: Http, slug: str, company: str | None = None) -> list[Job]:
    if slug.startswith("http"):
        url = slug
    elif re.fullmatch(r"[0-9a-fA-F-]{16,}", slug):
        url = f"https://recruiting.paylocity.com/Recruiting/v2/api/feed/jobs/{slug}"
    else:
        url = f"https://recruiting.paylocity.com/recruiting/jobs/All/{slug}"
    response = http.get(url, headers={"Accept": "application/json, application/xml, text/html, */*"})
    if response.status_code == 404:
        logger.warning("Paylocity board not found: %s", slug)
        return []
    ctype = response.headers.get("content-type") or ""
    jobs: list[Job] = []
    if "json" in ctype:
        payload = response.json() or {}
        items = payload.get("jobs") or payload.get("Jobs") or payload.get("data") or []
        for item in items:
            loc = item.get("JobLocation") or item.get("location") or {}
            location = loc if isinstance(loc, str) else join_location(
                loc.get("City"), loc.get("State"), loc.get("LocationDisplayName")
            )
            apply = item.get("ApplyUrl") or item.get("DisplayUrl") or item.get("url") or ""
            jobs.append(
                Job(
                    title=(item.get("Title") or item.get("title") or "").strip(),
                    company=item.get("CompanyName") or company or slug,
                    source="paylocity",
                    url=apply,
                    location=location,
                    date_posted=format_posted_date(item.get("PublishedDate") or item.get("CreatedUtc")),
                    description=html_to_text(item.get("Description") or item.get("description")),
                    apply_url=apply,
                    company_slug=slug,
                )
            )
        return jobs
    html = response.text
    pattern = re.compile(r'href="([^"]+/Jobs/(?:Details|Apply)/\d+/[^"]+)"[^>]*>\s*([^<]+)', re.IGNORECASE)
    seen: set[str] = set()
    for href, title in pattern.findall(html):
        title = html_to_text(title).strip()
        if not title or href in seen:
            continue
        seen.add(href)
        apply = urljoin("https://recruiting.paylocity.com", href)
        jobs.append(
            Job(
                title=title,
                company=company or slug,
                source="paylocity",
                url=apply,
                apply_url=apply,
                company_slug=slug,
            )
        )
    return jobs


def fetch_paycom(http: Http, slug: str, company: str | None = None) -> list[Job]:
    url = f"https://www.paycomonline.net/v4/ats/web.php/jobs?clientkey={slug}"
    response = http.get(url, headers={"Accept": "text/html, application/json, */*"})
    if response.status_code == 404:
        logger.warning("Paycom board not found: %s", slug)
        return []
    jobs: list[Job] = []
    html = response.text
    pattern = re.compile(
        r'href="([^"]*jobinfo.php[^"]+)"[^>]*>\s*([^<]+)',
        re.IGNORECASE,
    )
    seen: set[str] = set()
    for href, title in pattern.findall(html):
        title = html_to_text(title).strip()
        if not title or href in seen:
            continue
        seen.add(href)
        apply = urljoin(str(response.url), href.replace("&amp;", "&"))
        jobs.append(
            Job(
                title=title,
                company=company or slug,
                source="paycom",
                url=apply,
                apply_url=apply,
                company_slug=slug,
            )
        )
    return jobs


def fetch_successfactors(http: Http, slug: str, company: str | None = None) -> list[Job]:
    if slug.startswith("http"):
        board = slug
    else:
        board = f"https://career5.successfactors.eu/career?company={slug}&career_ns=job_listing_summary"
    response = http.get(board, headers={"Accept": "text/html, application/json, */*"})
    if response.status_code == 404:
        logger.warning("SuccessFactors board not found: %s", slug)
        return []
    jobs: list[Job] = []
    html = response.text
    pattern = re.compile(
        r'(?:jobTitle|job-title)[^>]*>([^<]+).{0,400}?(?:href|jobId)[="\']([^"\']+)',
        re.IGNORECASE | re.DOTALL,
    )
    seen: set[str] = set()
    for title, href in pattern.findall(html):
        title = html_to_text(title).strip()
        if not title or href in seen:
            continue
        seen.add(href)
        apply = href if href.startswith("http") else urljoin(str(response.url), href)
        jobs.append(
            Job(
                title=title,
                company=company or slug,
                source="successfactors",
                url=apply,
                apply_url=apply,
                company_slug=slug,
            )
        )
    if not jobs:
        simple = re.compile(r'href="([^"]*job[^"]*)"[^>]*>([^<]{8,120})', re.IGNORECASE)
        for href, title in simple.findall(html):
            title = html_to_text(title).strip()
            if not title or "javascript" in href.lower():
                continue
            apply = href if href.startswith("http") else urljoin(str(response.url), href)
            jobs.append(
                Job(
                    title=title,
                    company=company or slug,
                    source="successfactors",
                    url=apply,
                    apply_url=apply,
                    company_slug=slug,
                )
            )
            if len(jobs) >= 100:
                break
    return jobs


_YC_ROLE_PATHS = (
    "/jobs",
    "/jobs/l/software-engineer",
    "/jobs/l/designer",
    "/jobs/l/product-manager",
    "/jobs/l/science",
    "/jobs/l/operations",
    "/jobs/l/sales-manager",
    "/jobs/l/marketing",
    "/jobs/l/recruiting",
    "/jobs/l/legal",
    "/jobs/l/finance",
)


def _yc_jobs_from_html(page_html: str) -> list[dict[str, Any]]:
    match = re.search(r'data-page="([^"]+)"', page_html or "")
    if not match:
        return []
    try:
        payload = json.loads(html.unescape(match.group(1)))
    except Exception:
        return []
    props = payload.get("props") or {}
    items = props.get("jobs") or []
    return items if isinstance(items, list) else []


def fetch_ycombinator(http: Http, slug: str = "all", company: str | None = None) -> list[Job]:
    seen: set[str] = set()
    jobs: list[Job] = []
    html_headers = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}

    def _page(path: str) -> list[dict[str, Any]]:
        try:
            response = http.get(f"https://www.workatastartup.com{path}", headers=html_headers)
        except Exception:
            logger.exception("Work at a Startup request failed for %s", path)
            return []
        if response.status_code != 200:
            return []
        return _yc_jobs_from_html(response.text)

    for batch in map_pool(_page, list(_YC_ROLE_PATHS), max_workers=8):
        for item in batch:
            job_id = str(item.get("id") or "")
            if job_id and job_id in seen:
                continue
            if job_id:
                seen.add(job_id)
            location = item.get("location") or ""
            apply = (
                f"https://www.workatastartup.com/jobs/{job_id}"
                if job_id
                else (item.get("applyUrl") or "https://www.workatastartup.com/jobs")
            )
            jobs.append(
                Job(
                    title=(item.get("title") or "").strip(),
                    company=item.get("companyName") or company or "Y Combinator",
                    source="ycombinator",
                    url=apply,
                    location=location,
                    is_remote="remote" in location.lower(),
                    job_type=item.get("jobType") or "",
                    department=item.get("roleType") or "",
                    salary=str(item.get("salary") or ""),
                    description=html_to_text(item.get("companyOneLiner")),
                    apply_url=apply,
                    company_slug=str(item.get("companySlug") or ""),
                )
            )
    if not jobs:
        logger.warning("Y Combinator jobs feed returned no listings")
    return jobs


EXTRA_FETCHERS = {
    "bamboohr": fetch_bamboohr,
    "personio": fetch_personio,
    "breezy": fetch_breezy,
    "teamtailor": fetch_teamtailor,
    "pinpoint": fetch_pinpoint,
    "jazzhr": fetch_jazzhr,
    "manatal": fetch_manatal,
    "polymer": fetch_polymer,
    "icims": fetch_icims,
    "paylocity": fetch_paylocity,
    "paycom": fetch_paycom,
    "successfactors": fetch_successfactors,
    "ycombinator": fetch_ycombinator,
}


def extra_detect(host: str, path: str, raw: str) -> tuple[str, str] | None:
    slug = path.split("/")[0] if path else ""
    if host.endswith("bamboohr.com"):
        return "bamboohr", host.split(".")[0]
    if "jobs.personio." in host:
        return "personio", host.split(".")[0]
    if host.endswith("breezy.hr"):
        return "breezy", host.split(".")[0]
    if host.endswith("teamtailor.com"):
        return "teamtailor", host.split(".")[0]
    if host.endswith("pinpointhq.com"):
        return "pinpoint", host.split(".")[0]
    if host.endswith("applytojob.com") or host.endswith("jazz.co"):
        return "jazzhr", host.split(".")[0]
    if "manatal.com" in host or "careers-page.com" in host:
        return "manatal", slug or host.split("/")[-1]
    if "polymer.co" in host:
        return "polymer", slug
    if "icims.com" in host:
        name = host.split(".")[0].removeprefix("careers-")
        return "icims", name
    if "paylocity.com" in host:
        return "paylocity", raw
    if "paycomonline.net" in host:
        return "paycom", raw.split("clientkey=")[-1] if "clientkey=" in raw else slug
    if "successfactors" in host or "successfactors.eu" in host or "successfactors.com" in host:
        return "successfactors", raw
    if "ycombinator.com" in host or "workatastartup.com" in host:
        return "ycombinator", "all"
    return None
