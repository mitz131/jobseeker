"""SmartRecruiters public posting API (Mirabaud: company MirabaudCieSA).

  GET https://api.smartrecruiters.com/v1/companies/{company}/postings?country=ch&offset=N&limit=100
       -> postings (JSON, paged; `country` is the API's own filter, an ISO code)
  GET https://api.smartrecruiters.com/v1/companies/{company}/postings/{id}
       -> one posting; the ad is in jobAd.sections (company, job, qualifications, ...)

`job_url` is the public page for a posting; by default SmartRecruiters' own job page,
or the employer's careers page, e.g. "https://www.mirabaud.com/.../job-details/{id}".
"""

from collections.abc import Iterator

from ..html_text import html_to_text
from .base import JobDetail, JobRef

API = "https://api.smartrecruiters.com/v1/companies"
PAGE_SIZE = 100


class SmartRecruitersSource:
    def __init__(self, client, company: str, country: str = "", job_url: str = "", **_):
        self.client = client
        self.company = company
        self.country = country
        self.job_url = job_url or f"https://jobs.smartrecruiters.com/{company}/{{id}}"

    def list_jobs(self) -> Iterator[JobRef]:
        offset = 0
        while True:
            country = f"&country={self.country}" if self.country else ""
            page = self.client.get_json(
                f"{API}/{self.company}/postings?offset={offset}&limit={PAGE_SIZE}{country}")
            postings = page.get("content", [])
            for p in postings:
                loc = p.get("location") or {}
                yield JobRef(
                    job_id=p["id"],
                    title=(p.get("name") or "").strip(),
                    location=loc.get("fullLocation") or loc.get("city") or "",
                    url=self.job_url.format(id=p["id"]),
                    posted_on=(p.get("releasedDate") or "")[:10],
                )
            offset += len(postings)
            if not postings or offset >= page.get("totalFound", 0):
                break

    def fetch_detail(self, ref: JobRef) -> JobDetail:
        posting = self.client.get_json(f"{API}/{self.company}/postings/{ref.job_id}")
        sections = (posting.get("jobAd") or {}).get("sections") or {}
        html = "".join(f"<h2>{s['title']}</h2>{s['text']}" if s.get("title") else s.get("text", "")
                       for s in sections.values() if s.get("text"))
        return JobDetail(
            description_html=html,
            description=html_to_text(html),
            raw=posting,
            title=(posting.get("name") or "").strip() or None,
            posted_on=(posting.get("releasedDate") or "")[:10] or None,
        )
