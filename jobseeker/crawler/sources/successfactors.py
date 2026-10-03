"""SAP SuccessFactors Career Site Builder sites (Nestle, BCV).

Two generations of the search page exist:

  listing = "html" (Nestle): results are server-rendered
    GET  {base}/search/?q=...&optionsFacetsDD_country=CH&startrow=N  -> listing (HTML)
  listing = "api" (BCV): results come from the site's own JSON endpoint, which
    needs the session cookie and the CSRF token embedded in the search page
    POST {base}/services/recruiting/v1/jobs                         -> listing (JSON)

Either way the job page is HTML:
  GET {base}/job/<slug>/<id>/                                       -> detail (HTML)
"""

import re
import urllib.parse
from collections.abc import Iterator
from html import unescape

from bs4 import BeautifulSoup, Tag

from ..html_text import html_to_text
from .base import JobDetail, JobRef

JOB_ID_RE = re.compile(r"^/job/.+/(\d+)/?$")  # /job/<slug>/<id>/
TOTAL_RE = re.compile(r"of\s*([\d,.]+)")
# Not HTML: the token is set in an inline script
CSRF_RE = re.compile(r'var CSRFToken = "([^"]+)"')


def _text(el: Tag) -> str:
    return " ".join(el.get_text(" ").split())


def _is_description(tag: Tag, classes: set[str]) -> bool:
    return tag.get("itemprop") == "description" or bool(
        classes & {c.lower() for c in tag.get("class") or []})


def extract_description(page_html: str, classes: tuple[str, ...] = ("jobdescription",)) -> str:
    """Description HTML from elements marked itemprop="description" or carrying one
    of `classes`. Some sites split the posting into several such blocks (BCV: intro,
    role, profile); a marked element nested in another one is part of that block.
    Also used for other sites with server-rendered job pages."""
    wanted = {c.lower() for c in classes}
    soup = BeautifulSoup(page_html, "html.parser")
    blocks = []
    for el in soup.find_all(lambda t: _is_description(t, wanted)):
        if any(_is_description(p, wanted) for p in el.parents if isinstance(p, Tag)):
            continue
        html = el.decode_contents(formatter="html5").strip()
        if html and html not in blocks:  # skip repeated copies (e.g. mobile + desktop)
            blocks.append(html)
    return "\n".join(blocks)


def page_locations(page_html: str) -> str:
    """All locations listed on a job page, in order, without the page's repeated copies."""
    locs = []
    for el in BeautifulSoup(page_html, "html.parser").select("span.jobGeoLocation"):
        loc = _text(el)
        if loc and loc not in locs:
            locs.append(loc)
    return " / ".join(locs)


class SuccessFactorsSource:
    def __init__(self, client, base_url: str, search: str = "", facets: dict | None = None,
                 listing: str = "html", locale: str = "en_US", **_):
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.search = search
        # html listing: e.g. {"country": "CH"} -> optionsFacetsDD_country=CH
        self.facets = facets or {}
        if listing not in ("html", "api"):
            raise ValueError(f"listing must be 'html' or 'api', not {listing!r}")
        self.listing = listing
        self.locale = locale

    def _search_url(self, startrow: int) -> str:
        params = {"q": self.search}
        params.update({f"optionsFacetsDD_{k}": v for k, v in self.facets.items()})
        # A fixed sort keeps pagination stable while we page through
        params.update({"sortColumn": "referencedate", "sortDirection": "desc",
                       "startrow": startrow})
        return f"{self.base_url}/search/?{urllib.parse.urlencode(params)}"

    def list_jobs(self) -> Iterator[JobRef]:
        return self._list_api() if self.listing == "api" else self._list_html()

    def _list_api(self) -> Iterator[JobRef]:
        token = CSRF_RE.search(self.client.get_text(f"{self.base_url}/search/?q="))
        if not token:
            raise RuntimeError("CSRF token not found on search page")
        page_number, seen = 0, set()
        while True:
            data = self.client.post_json(
                f"{self.base_url}/services/recruiting/v1/jobs",
                {"locale": self.locale, "pageNumber": page_number, "sortBy": "date",
                 "keywords": self.search, "location": "", "facetFilters": {}, "brand": "",
                 "skills": [], "categoryId": 0, "alertId": "", "rcmCandidateId": ""},
                headers={"X-CSRF-Token": token.group(1)},
            )
            results = data.get("jobSearchResult") or []
            for item in results:
                job = item.get("response", {})
                if not job.get("id") or job["id"] in seen:
                    continue
                seen.add(job["id"])
                start = job.get("unifiedStandardStart") or ""  # dd/mm/yyyy
                day, month, year = (start.split("/") + ["", "", ""])[:3]
                yield JobRef(
                    job_id=job["id"],
                    title=unescape(job.get("unifiedStandardTitle", "")),
                    location=", ".join(job.get("filter1") or []),
                    url=f"{self.base_url}/job/{job.get('urlTitle', 'job')}/{job['id']}-{self.locale}/",
                    posted_on=f"{year}-{month}-{day}" if year else start,
                )
            page_number += 1
            if not results or len(seen) >= data.get("totalJobs", 0):
                break

    def _list_html(self) -> Iterator[JobRef]:
        startrow, seen = 0, set()
        while True:
            soup = BeautifulSoup(self.client.get_text(self._search_url(startrow)), "html.parser")
            rows = soup.select("tr.data-row")
            found = 0
            for row in rows or [soup]:
                link = row.find("a", href=JOB_ID_RE)
                if not link or JOB_ID_RE.search(link["href"]).group(1) in seen:
                    continue
                job_id = JOB_ID_RE.search(link["href"]).group(1)
                seen.add(job_id)
                found += 1
                loc = row.select_one("span.jobLocation")
                if loc:
                    for badge in loc.find_all("small"):  # "+2 more..." on multi-location jobs
                        badge.decompose()
                date = row.select_one("span.jobDate")
                yield JobRef(
                    job_id=job_id,
                    title=link.get_text().strip(),
                    location=_text(loc) if loc else "",
                    url=f"{self.base_url}{link['href']}",
                    posted_on=_text(date) if date else "",
                )
            label = soup.select_one(".paginationLabel")
            total = TOTAL_RE.search(label.get_text()) if label else None
            total = int(re.sub(r"\D", "", total.group(1))) if total else None
            # Advance by what the page actually returned; the site decides the page size
            startrow += len(rows) if rows else found
            if not found or (total is not None and startrow >= total):
                break

    def fetch_detail(self, ref: JobRef) -> JobDetail:
        page = self.client.get_text(ref.url)
        html = extract_description(page)
        if not html_to_text(html):
            # e.g. the posting was withdrawn: don't store an empty job, retry next run
            raise ValueError(f"No description found on {ref.url}")
        return JobDetail(description_html=html, description=html_to_text(html),
                         raw={"url": ref.url}, location=page_locations(page) or None)
