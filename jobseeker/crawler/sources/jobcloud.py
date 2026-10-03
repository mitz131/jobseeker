"""JobCloud company job lists (Salt), the embeddable list behind jobs.ch / jobup.ch.

  GET https://company.jobcloud.ch/{lang}/job-list/{company}  -> listing; every job
      is embedded in the page's Next.js data as {"id": ..., "title": ..., ...},
      even though the page only displays the first few
  GET https://company.jobcloud.ch/{lang}/jobs/{company}/{id} -> detail (HTML,
      <div class="job-description">)
"""

import json
import re
from collections.abc import Iterator

from ..html_text import html_to_text
from .base import JobDetail, JobRef
from .successfactors import extract_description

BASE_URL = "https://company.jobcloud.ch"
PUSH_RE = re.compile(r"self\.__next_f\.push\((\[.*?\])\)</script>", re.S)
UUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
JOB_START_RE = re.compile(r'\{\s*"id"\s*:\s*"%s"\s*,\s*"title"\s*:' % UUID_RE)


def embedded_payload(page_html: str) -> str:
    """The page's Next.js data, as one string."""
    chunks = (json.loads(p) for p in PUSH_RE.findall(page_html))
    return "".join(c[1] for c in chunks if len(c) > 1 and isinstance(c[1], str))


def embedded_jobs(page_html: str) -> list[dict]:
    payload, decoder, jobs = embedded_payload(page_html), json.JSONDecoder(), []
    for m in JOB_START_RE.finditer(payload):
        job, _ = decoder.raw_decode(payload, m.start())
        jobs.append(job)
    return jobs


class JobCloudSource:
    def __init__(self, client, company: str, lang: str = "fr", **_):
        self.client = client
        self.company = company  # slug in the list URL, e.g. "salt-mobile-sa"
        self.lang = lang

    def list_jobs(self) -> Iterator[JobRef]:
        page = self.client.get_text(f"{BASE_URL}/{self.lang}/job-list/{self.company}")
        jobs = embedded_jobs(page)
        if not jobs:
            raise RuntimeError(f"No jobs found in JobCloud list for {self.company}; layout may have changed")
        seen = set()
        for job in jobs:
            if job["id"] in seen:
                continue
            seen.add(job["id"])
            yield JobRef(
                job_id=job["id"],
                title=job.get("title", ""),
                location=job.get("location") or "",
                url=f"{BASE_URL}/{self.lang}/jobs/{self.company}/{job['id']}",
                extra={"employmentPct": job.get("employmentPct")},
            )

    def fetch_detail(self, ref: JobRef) -> JobDetail:
        html = extract_description(self.client.get_text(ref.url), classes=("job-description",))
        if not html_to_text(html):
            raise ValueError(f"No description found on {ref.url}")
        return JobDetail(description_html=html, description=html_to_text(html), raw={"url": ref.url})
