"""Radancy (TalentBrew) career sites, e.g. Cargill's careers.cargill.com.

These sites' robots.txt disallows /search-jobs/, so the source uses a **location page**
instead, which the sitemap links and robots.txt allows, e.g. for Switzerland:

  GET https://careers.cargill.com/en/location/switzerland-jobs/23251/2658434/2
      -> server-rendered list: <a data-job-id=… href="/en/job/<city>/<slug>/<org>/<id>">
         <h3>title</h3><span class="job-location">Geneva, Switzerland | Schiphol, Netherlands</span>
         The results block says how many pages there are (data-total-pages, 15 jobs each).
  GET the job's page
      -> a schema.org JobPosting JSON-LD with the description and datePosted

Paging isn't implemented: the paging URL can't be observed while every job fits on the
first page, so a list with more pages fails loudly rather than being read half.
"""

import re
from collections.abc import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..html_text import html_to_text
from .base import JobDetail, JobRef
from .vaudoise import find_job_posting


def swiss_locations(text: str, country: str = "Switzerland") -> str:
    """"Geneva, Switzerland | Schiphol, Netherlands" -> "Geneva": the location page is
    one country's, so places elsewhere are dropped, and so is the country name."""
    suffix = re.compile(rf",\s*{re.escape(country)}$", re.I)
    places = [p.strip() for p in text.split("|")]
    return " / ".join(suffix.sub("", p) for p in places if suffix.search(p))


class RadancySource:
    def __init__(self, client, location_url: str, country: str = "Switzerland", **_):
        self.client = client
        self.location_url = location_url
        self.country = country

    def list_jobs(self) -> Iterator[JobRef]:
        soup = BeautifulSoup(self.client.get_text(self.location_url), "html.parser")
        results = soup.find(attrs={"data-total-pages": True})
        if results is None:
            raise RuntimeError(f"No search results block on {self.location_url}; page layout may have changed")
        pages = int(results.get("data-total-pages") or 0)
        if pages > 1:
            raise RuntimeError(f"{self.location_url} has {pages} pages of jobs; paging is not implemented yet "
                               "(only the first page could be read)")
        seen = set()
        for link in results.find_all("a", attrs={"data-job-id": True}, href=True):
            job_id = link["data-job-id"]
            if job_id in seen:
                continue
            seen.add(job_id)
            title = link.find("h3")
            place = link.find(class_="job-location")
            yield JobRef(
                job_id=job_id,
                title=" ".join((title or link).get_text(" ").split()),
                location=swiss_locations(place.get_text(" ") if place else "", self.country),
                url=urljoin(self.location_url, link["href"]),
            )

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
