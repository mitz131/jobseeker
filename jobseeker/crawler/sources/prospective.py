"""Prospective career centres, e.g. Generali Switzerland's jobs.generali.ch.

  GET {base_url}/?lang=<lang>&offset=N&limit=M
      -> server-rendered list: a.job links to /offene-stellen/<slug>/<uuid> with the
         title (span.job-title) and place of work (span.place-of-work), and the total
         count (span.total); the page's own pager steps by 15, `limit` takes more
  GET the job's page
      -> schema.org JobPosting JSON-LD: the whole ad in `description`, datePosted,
         jobLocation, employmentType, validThrough

The career centre is the employer's own, for its Swiss jobs: no country filter.
"""

import re
from collections.abc import Iterator
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup, Tag

from ..html_text import html_to_text
from .base import JobDetail, JobRef
from .vaudoise import find_job_posting

PAGE_SIZE = 100
MAX_PAGES = 20
JOB_ID_RE = re.compile(r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/?$")


def _text(el: Tag | None) -> str:
    return " ".join(el.get_text(" ").split()) if el else ""


def posting_location(job: dict) -> str:
    """The JSON-LD jobLocation(s) as "postcode locality", e.g. "8640 Rapperswil": the
    postcode places the job when the name alone doesn't (Rapperswil, Buchs, Genève 15)."""
    places = job.get("jobLocation") or []
    places = places if isinstance(places, list) else [places]
    names = []
    for p in places:
        address = (p.get("address") or {}) if isinstance(p, dict) else {}
        name = " ".join(str(address.get(k) or "").strip() for k in ("postalCode", "addressLocality")).strip()
        if name:
            names.append(name)
    return " / ".join(names)


class ProspectiveSource:
    def __init__(self, client, base_url: str, lang: str = "de", **_):
        self.client = client
        self.base_url = base_url.rstrip("/")   # e.g. https://jobs.generali.ch
        self.lang = lang

    def list_jobs(self) -> Iterator[JobRef]:
        offset, seen = 0, set()
        for _ in range(MAX_PAGES):
            url = f"{self.base_url}/?{urlencode({'lang': self.lang, 'offset': offset, 'limit': PAGE_SIZE})}"
            soup = BeautifulSoup(self.client.get_text(url), "html.parser")
            total = soup.select_one("#header-content .total, .jobs-total .total")
            if not total:
                raise RuntimeError(f"No job count on {url}; page layout may have changed")
            links = [a for a in soup.select("a.job[href]") if JOB_ID_RE.search(a["href"])]
            for a in links:
                job_id = JOB_ID_RE.search(a["href"])[1]
                if job_id in seen:
                    continue
                seen.add(job_id)
                yield JobRef(
                    job_id=job_id,
                    title=_text(a.select_one(".job-title")) or a.get("title", "").strip(),
                    location=_text(a.select_one(".place-of-work")),
                    url=urljoin(url, a["href"]),
                )
            offset += len(links)
            if not links or offset >= int(re.sub(r"\D", "", _text(total)) or 0):
                return
        raise RuntimeError(f"{self.base_url}: more than {MAX_PAGES} pages of results")

    def fetch_detail(self, ref: JobRef) -> JobDetail:
        try:
            job = find_job_posting(self.client.get_text(ref.url))
        except ValueError as e:
            raise RuntimeError(f"{e} on {ref.url}; page layout may have changed") from e
        html = job.get("description") or ""
        if not html_to_text(html):
            raise RuntimeError(f"No job description on {ref.url}")
        return JobDetail(
            description_html=html,
            description=html_to_text(html),
            raw={"url": ref.url, "title": job.get("title"), "employment_type": job.get("employmentType"),
                 "valid_through": job.get("validThrough"),
                 "employer": (job.get("hiringOrganization") or {}).get("name"),
                 "location": posting_location(job)},
            location=posting_location(job) or None,
            posted_on=(job.get("datePosted") or "")[:10] or None,
        )
