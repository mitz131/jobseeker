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
from html import unescape

from ..html_text import html_to_text
from .base import JobDetail, JobRef

CARD_RE = re.compile(
    r'<a\s[^>]*?href="([^"]+)"[^>]*?data-shared-job-id="(\d+)"[^>]*>(.*?)</a>', re.S)
TITLE_RE = re.compile(r'data-tui="job-title"\s*>(.*?)</h2>', re.S)
LOCATION_RE = re.compile(r'data-tui="location"\s*>(.*?)</td>', re.S)
POSTED_RE = re.compile(r"Publi(?:&#233;|é) le\s*:\s*([^<]+)<")
LD_JSON_RE = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)


def _clean(fragment: str) -> str:
    return html_to_text(unescape(fragment)).strip()


def find_job_posting(page_html: str) -> dict:
    for block in LD_JSON_RE.findall(page_html):
        data = json.loads(block)
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
    raise ValueError("No JobPosting JSON-LD found")


class VaudoiseSource:
    def __init__(self, client, listing_url: str, **_):
        self.client = client
        self.listing_url = listing_url

    def list_jobs(self) -> Iterator[JobRef]:
        page = self.client.get_text(self.listing_url)
        seen = set()
        for url, job_id, card in CARD_RE.findall(page):
            if job_id in seen:
                continue
            seen.add(job_id)
            title = TITLE_RE.search(card)
            loc = LOCATION_RE.search(card)
            posted = POSTED_RE.search(card)
            yield JobRef(
                job_id=job_id,
                title=_clean(title.group(1)) if title else "",
                location=_clean(loc.group(1)) if loc else "",
                url=unescape(url),
                posted_on=posted.group(1).strip() if posted else "",
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
