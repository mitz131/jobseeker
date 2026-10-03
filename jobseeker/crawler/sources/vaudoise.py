"""Vaudoise Assurances.

The careers page renders every open job server-side (no paging); each card links
to the job on Softgarden, Vaudoise's applicant tracking system:

  GET https://www.vaudoise.ch/fr/carrieres/postes-disponibles  -> listing (HTML)
  GET https://vaudoise.softgarden.io/job/{id}                   -> detail; the job is
       embedded as schema.org JobPosting JSON-LD
"""

import json
import re
from collections.abc import Iterator

from bs4 import BeautifulSoup, Tag

from ..html_text import html_to_text
from .base import JobDetail, JobRef

POSTED_RE = re.compile(r"Publié le\s*:\s*(.+)")


def _text(el: Tag | None) -> str:
    return " ".join(el.get_text(" ").split()) if el else ""


def find_job_posting(page_html: str) -> dict:
    soup = BeautifulSoup(page_html, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        data = json.loads(script.get_text())
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
    raise ValueError("No JobPosting JSON-LD found")


class VaudoiseSource:
    def __init__(self, client, listing_url: str, **_):
        self.client = client
        self.listing_url = listing_url

    def list_jobs(self) -> Iterator[JobRef]:
        soup = BeautifulSoup(self.client.get_text(self.listing_url), "html.parser")
        seen = set()
        for card in soup.find_all("a", attrs={"data-shared-job-id": True}):
            job_id = card["data-shared-job-id"]
            if job_id in seen:
                continue
            seen.add(job_id)
            posted = card.find(string=POSTED_RE)
            yield JobRef(
                job_id=job_id,
                title=_text(card.find(attrs={"data-tui": "job-title"})),
                location=_text(card.find(attrs={"data-tui": "location"})),
                url=card["href"],
                posted_on=POSTED_RE.search(posted).group(1).strip() if posted else "",
            )
        if not seen:
            raise RuntimeError(f"No jobs found on {self.listing_url}; page layout may have changed")

    def fetch_detail(self, ref: JobRef) -> JobDetail:
        job = find_job_posting(self.client.get_text(ref.url))
        html = job.get("description", "")
        return JobDetail(
            description_html=html,
            description=html_to_text(html),
            raw=job,
            title=(job.get("title") or "").strip() or None,
            posted_on=(job.get("datePosted") or "")[:10] or None,
        )
