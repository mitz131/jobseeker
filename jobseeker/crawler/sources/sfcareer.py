"""SAP SuccessFactors classic career portal (Pictet: career012.successfactors.eu, company
banquepict). Older than the Career Site Builder sites in successfactors.py: the search page
is built in the browser, but the portal also publishes all postings as one XML feed.

  GET {host}/career?company={company}&career_ns=job_listing_summary&resultType=XML
       -> every posting worldwide: title, ReqId and the description (HTML), no location
  GET {host}/career?company={company}&career_ns=job_listing&career_job_req_id={id}
       -> the job page; its header line gives the location:
          "Requisition ID 125136 - Posted - Germany - Frankfurt - (Administration) - ..."

The feed has no location, so listing reads each job's header and keeps the ones in
`country`: one page per posting on every run. The portal shows no posting date.
"""

import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from html import unescape

from ..html_text import html_to_text
from .base import JobDetail, JobRef

HEADER_RE = re.compile(r"Requisition ID&nbsp;<b>\d+</b>(.*?)</div>", re.S)
BOLD_RE = re.compile(r"<b>([^<]*)</b>")   # the posted date is <b id=...>, so it is skipped

log = logging.getLogger(__name__)


def job_place(page_html: str) -> tuple[str, str]:
    """(country, city) from a job page's header line."""
    m = HEADER_RE.search(page_html)
    parts = [unescape(p).strip() for p in BOLD_RE.findall(m.group(1))] if m else []
    if len(parts) < 2:
        raise ValueError("Location not found in the job page header")
    return parts[0], parts[1]


class SFCareerSource:
    def __init__(self, client, host: str, company: str, country: str, **_):
        self.client = client
        self.host = host.rstrip("/")
        self.company = company
        self.country = country
        self._feed: dict[str, ET.Element] = {}

    def job_url(self, req_id: str) -> str:
        return f"{self.host}/career?company={self.company}&career_ns=job_listing&career_job_req_id={req_id}"

    def list_jobs(self) -> Iterator[JobRef]:
        xml = self.client.get_text(
            f"{self.host}/career?company={self.company}&career_ns=job_listing_summary&resultType=XML")
        root = ET.fromstring(xml)
        if root.tag != "Job-Listing":
            raise RuntimeError(f"Unexpected job feed for {self.company}: <{root.tag}>")
        self._feed = {job.findtext("ReqId", "").strip(): job for job in root.findall("Job")}
        failed = 0
        for req_id, job in self._feed.items():
            url = self.job_url(req_id)
            try:
                country, city = job_place(self.client.get_text(url))
            except Exception as e:   # one bad page shouldn't sink the listing
                log.warning("%s: no location for %s: %s", self.company, req_id, e)
                failed += 1
                continue
            if country.casefold() != self.country.casefold():
                continue
            yield JobRef(job_id=req_id, title=unescape(job.findtext("JobTitle", "")).strip(),
                         location=f"{city}, {country}", url=url)
        if self._feed and failed == len(self._feed):
            raise RuntimeError(f"No job page of {self.company} had a location; page layout may have changed")

    def fetch_detail(self, ref: JobRef) -> JobDetail:
        job = self._feed[ref.job_id]   # the feed already has the description
        html = job.findtext("Job-Description", "")
        return JobDetail(
            description_html=html,
            description=html_to_text(html),
            raw={child.tag: (child.text or "").strip() for child in job if child.tag != "Job-Description"},
        )
