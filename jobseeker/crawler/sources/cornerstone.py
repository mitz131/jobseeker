"""Cornerstone OnDemand career sites, e.g. IATA's iata.csod.com.

  GET  {base_url}/ux/ats/careersite/{site}/home?c={corp}
       -> HTML whose inline `csod.context = {...}` holds a guest token (JWT) and the
          regional API host (endpoints.cloud, e.g. https://eu-fra.api.csod.com/)
  POST {cloud}rec-job-search/external/jobs                   (Bearer token)
       {"careerSiteId": site, "countryCodes": ["ch"], "pageNumber": N, "pageSize": 25, ...}
       -> data.requisitions (id, title, locations [{city, country}], posting date
          dd/mm/yyyy, plain-text description) and data.totalCount
  GET  {base_url}/services/x/job-requisition/v2/requisitions/{id}/jobDetails?cultureId=..
       (Bearer token) -> data[0]: the ad as HTML, primaryLocation, companyApplyUrl

The search's own country filter is used; each job's countries are still checked.
The career site's robots.txt asks for a crawl delay (IATA: 10 s), kept between
requests to `base_url`; the API host is a separate one.
"""

import json
import re
import time
from collections.abc import Iterator

from ..html_text import html_to_text
from .base import JobDetail, JobRef

PAGE_SIZE = 25
MAX_PAGES = 20
CONTEXT_RE = re.compile(r"csod\.context\s*=\s*")
DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def iso_date(text: str) -> str:
    m = DATE_RE.search(text or "")
    return f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}" if m else ""


def page_context(page_html: str) -> dict:
    """The `csod.context = {...}` object of the career site page."""
    for m in CONTEXT_RE.finditer(page_html):
        if page_html[m.end()] == "{":
            return json.JSONDecoder().raw_decode(page_html, m.end())[0]
    raise RuntimeError("No csod.context on the career site page; page layout may have changed")


def place(loc: dict) -> str:
    return ", ".join(p for p in (loc.get("city"), loc.get("country")) if p)


class CornerstoneSource:
    def __init__(self, client, base_url: str, corp: str, career_site: int = 1, culture_id: int = 2,
                 country: str = "CH", crawl_delay: float = 10, **_):
        self.client = client
        self.base_url = base_url.rstrip("/")   # e.g. https://iata.csod.com
        self.corp = corp                        # the c= parameter, e.g. iata
        self.career_site = career_site
        self.culture_id = culture_id
        self.country = country
        self.crawl_delay = crawl_delay
        self._last_site_request = None
        self._token = self._cloud = None

    def _site(self, fetch, url: str):
        """A request to the career site itself, spaced by crawl_delay."""
        if self._last_site_request is not None:
            time.sleep(max(0.0, self.crawl_delay - (time.monotonic() - self._last_site_request)))
        try:
            return fetch(url)
        finally:
            self._last_site_request = time.monotonic()

    def _session(self) -> dict:
        if not self._token:
            ctx = page_context(self._site(self.client.get_text,
                                          f"{self.base_url}/ux/ats/careersite/{self.career_site}/home?c={self.corp}"))
            self._token = ctx.get("token")
            self._cloud = (ctx.get("endpoints") or {}).get("cloud")
            if not self._token or not self._cloud:
                raise RuntimeError(f"No token or API host in csod.context on {self.base_url}")
        return {"Authorization": f"Bearer {self._token}"}

    def list_jobs(self) -> Iterator[JobRef]:
        headers = self._session()
        for page in range(1, MAX_PAGES + 1):
            data = self.client.post_json(f"{self._cloud.rstrip('/')}/rec-job-search/external/jobs", {
                "careerSiteId": self.career_site, "careerSitePageId": self.career_site, "pageNumber": page,
                "pageSize": PAGE_SIZE, "cultureId": self.culture_id, "searchText": "", "cultureName": "",
                "states": [], "countryCodes": [self.country.lower()], "cities": [], "placeID": "",
                "radius": None, "postingsWithinDays": None, "customFieldCheckboxKeys": [],
                "customFieldDropdowns": [], "customFieldRadios": []}, headers=headers)["data"]
            reqs = data.get("requisitions") or []
            for r in reqs:
                # Swiss first: the job's place is taken from the first location
                locations = sorted(r.get("locations") or [],
                                   key=lambda loc: (loc.get("country") or "").upper() != self.country.upper())
                if not locations or (locations[0].get("country") or "").upper() != self.country.upper():
                    continue
                job_id = str(r["requisitionId"])
                yield JobRef(
                    job_id=job_id,
                    title=" ".join((r.get("displayJobTitle") or "").replace("​", "").split()),
                    location=" / ".join(place(loc) for loc in locations),
                    url=f"{self.base_url}/ux/ats/careersite/{self.career_site}/home/requisition/{job_id}?c={self.corp}",
                    posted_on=iso_date(r.get("postingEffectiveDate")),
                )
            if not reqs or page * PAGE_SIZE >= data.get("totalCount", 0):
                return
        raise RuntimeError(f"{self.base_url}: more than {MAX_PAGES} pages of results")

    def fetch_detail(self, ref: JobRef) -> JobDetail:
        headers = self._session()
        url = (f"{self.base_url}/services/x/job-requisition/v2/requisitions/{ref.job_id}"
               f"/jobDetails?cultureId={self.culture_id}")
        data = self._site(lambda u: self.client.get_json(u, headers=headers), url).get("data")
        job = data[0] if isinstance(data, list) and data else data
        html = (job or {}).get("externalDescription") or ""
        if not html.strip():
            raise RuntimeError(f"No job description for requisition {ref.job_id} on {self.base_url}")
        primary = job.get("primaryLocation") or {}
        return JobDetail(
            description_html=html,
            description=html_to_text(html),
            raw={"url": ref.url, "ref": job.get("ref"), "open_date": job.get("openDate"),
                 "primary_location": {k: primary.get(k) for k in ("title", "city", "country", "postalCode")}},
            title=" ".join((job.get("displayTitle") or "").split()) or None,
            url=job.get("companyApplyUrl") or None,
        )
