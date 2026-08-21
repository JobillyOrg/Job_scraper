# USA job scraper

A personal job-search tool. It collects **US and remote** openings for a role you type in, then shows them in a local web page with the job description, company, location, posted date, source, and apply link.

It does not log in. It only reads public listings:

1. **Job boards** — Indeed, LinkedIn, ZipRecruiter, and Freehire (search by role and location).
2. **Company career pages** — public ATS boards you list in `config.yaml` (Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, BambooHR, Personio, Workday, iCIMS, Paylocity, Paycom, SuccessFactors, Breezy, Teamtailor, Pinpoint, JazzHR, Manatal, Polymer).
3. **Y Combinator** — public Work at a Startup listings (one switch, not a per-company slug).

Results are stored in SQLite (`output/jobs.db`) and also written to `output/jobs.csv`. Fetching the same posting again updates it instead of duplicating it. The same title at the same company is grouped across cities; click a row to read the JD and open each location’s posting.

## Setup

Python 3.10+.

```powershell
cd "C:\Users\avina\OneDrive\Desktop\job scraper"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Edit `config.yaml` for the default search query and the company career-page slugs you care about.

## Web UI

This is the usual way to run it:

```powershell
python -m job_scraper.web
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

- Type a role (for example `software engineer`) and an optional location.
- Check the boards and ATS sources you want. LinkedIn and Workday start unchecked (slow / easy to rate-limit).
- Turn **USA / remote only** on to drop non-US postings.
- Click **Fetch jobs**. Rows load into the table; click a row for the description.

Company lists for ATS chips still come from `config.yaml`. Empty ATS entries (JazzHR, iCIMS, and similar) appear as chips but return nothing until you add a slug or careers URL.

## Command line

```powershell
python -m job_scraper
python -m job_scraper --query "data engineer" --location "Austin, TX"
python -m job_scraper --ats-only
python -m job_scraper --boards-only --no-linkedin
python -m job_scraper --out output/jobs.json
```

## What each source needs

| Source | What you put in `config.yaml` |
| --- | --- |
| Indeed, ZipRecruiter, LinkedIn | `query` and `location`. Keep `country_indeed: USA`. |
| Freehire | Same search query. Public Freehire job index (`countries=us` when USA-only is on). |
| Greenhouse | Slug from `boards.greenhouse.io/stripe` → `stripe` |
| Lever | Slug from `jobs.lever.co/spotify` → `spotify` |
| Ashby | Slug from `jobs.ashbyhq.com/openai` → `openai` |
| Workable | Slug from `apply.workable.com/huggingface` → `huggingface` |
| SmartRecruiters | Identifier from `jobs.smartrecruiters.com/Visa` → `Visa` (case can matter) |
| Recruitee | Subdomain from `acme.recruitee.com` → `acme` |
| BambooHR | Subdomain from `flyio.bamboohr.com/careers` → `flyio` |
| Personio | Subdomain from `acme.jobs.personio.com` → `acme` |
| Breezy | Subdomain from `acme.breezy.hr` → `acme` |
| Teamtailor | Subdomain from `acme.teamtailor.com` → `acme` |
| Pinpoint | Subdomain from `acme.pinpointhq.com` → `acme` |
| JazzHR | Subdomain from `acme.applytojob.com` → `acme` |
| Manatal | Career-page slug (from `careers-page.com/acme` or the Manatal board id) |
| Polymer | Organization slug from the Polymer hire board |
| iCIMS | Company id from `careers-{id}.icims.com`, or the full search URL |
| Paylocity | Company GUID or full `recruiting.paylocity.com` jobs URL |
| Paycom | `clientkey` from the Paycom jobs URL |
| SuccessFactors | Company id or the full career-site URL |
| Workday | Full board URL, e.g. `https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite` |
| Y Combinator | `ycombinator: [all]` |

Workday needs the real careers URL (tenant + `wd1`/`wd5` shard + site name), not a company name. For Greenhouse, Lever, Ashby, Workable, and Workday you can paste that full URL instead of a slug.

```yaml
ats:
  greenhouse:
    - stripe
    - https://boards.greenhouse.io/airbnb
  workday:
    - name: NVIDIA
      url: https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite
  ycombinator:
    - all
```

LinkedIn rate-limits aggressively on a single IP. Leave it unchecked in the UI unless you need it. Optional proxies:

```yaml
proxies:
  - "user:pass@host:port"
```

This is for personal job search against public listings. Respect each site’s terms of use.
