from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Job:
    title: str
    company: str
    source: str
    url: str
    location: str = ""
    is_remote: bool | None = None
    job_type: str = ""
    department: str = ""
    date_posted: str = ""
    description: str = ""
    salary: str = ""
    apply_url: str = ""
    company_slug: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        extra = row.pop("extra") or {}
        row.update({k: v for k, v in extra.items() if k not in row})
        return row

    def to_public(self) -> dict[str, Any]:
        from job_scraper.normalize import format_posted_date

        description = (self.description or "").strip()
        return {
            "title": self.title,
            "company": self.company,
            "source": self.source,
            "url": self.url or self.apply_url,
            "location": self.location,
            "is_remote": self.is_remote,
            "job_type": self.job_type,
            "department": self.department,
            "date_posted": format_posted_date(self.date_posted) or str(self.date_posted or ""),
            "salary": self.salary,
            "apply_url": self.apply_url or self.url,
            "description": description,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Job:
        remote = row.get("is_remote")
        if remote is True or str(remote).lower() in {"true", "1"}:
            is_remote: bool | None = True
        elif remote is False or str(remote).lower() in {"false", "0"}:
            is_remote = False
        else:
            is_remote = None
        return cls(
            title=str(row.get("title") or ""),
            company=str(row.get("company") or ""),
            source=str(row.get("source") or ""),
            url=str(row.get("url") or row.get("apply_url") or ""),
            location=str(row.get("location") or ""),
            is_remote=is_remote,
            job_type=str(row.get("job_type") or ""),
            department=str(row.get("department") or ""),
            date_posted=str(row.get("date_posted") or ""),
            description=str(row.get("description") or ""),
            salary=str(row.get("salary") or ""),
            apply_url=str(row.get("apply_url") or row.get("url") or ""),
            company_slug=str(row.get("company_slug") or ""),
        )
