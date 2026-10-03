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
from html.parser import HTMLParser

from ..html_text import html_to_text
from .base import JobDetail, JobRef

JOB_LINK_RE = re.compile(r'href="(/job/[^"]+?/(\d+)/?)"[^>]*>([^<]+)<')
MORE_LOCATIONS_RE = re.compile(r"<small.*?</small>", re.S)  # "+2 more..." badge
LOCATION_RE = re.compile(r'<span class="jobLocation">\s*(.*?)\s*</span>', re.S)
DATE_RE = re.compile(r'<span class="jobDate">\s*(.*?)\s*</span>', re.S)
TOTAL_RE = re.compile(r'paginationLabel.*?of\s*<b>\s*([\d,.]+)\s*</b>', re.S)
ROW_RE = re.compile(r'<tr class="data-row.*?</tr>', re.S)
CSRF_RE = re.compile(r'var CSRFToken = "([^"]+)"')
# Job page: one span per location (the listing only shows the first, plus "+2 more")
GEO_LOCATION_RE = re.compile(r'<span class="jobGeoLocation">(.*?)</span>\s*(?=<span class="jobGeoLocation"|</p>)', re.S)
# Elements that never get a closing tag; they must not count towards nesting depth
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
             "param", "source", "track", "wbr"}


class _DescriptionExtractor(HTMLParser):
    """Collects the inner HTML of every top-level element whose class or itemprop
    marks it as the job description. Some sites split the posting into several
    such blocks (BCV: intro, role, profile); nested markers are part of the
    enclosing block."""

    def __init__(self, classes: tuple[str, ...] = ("jobdescription",)):
        super().__init__(convert_charrefs=False)
        self.classes = set(classes)
        self.depth = 0
        self.blocks: list[str] = []
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if self.depth:
            if tag not in VOID_TAGS:
                self.depth += 1
            self.parts.append(self.get_starttag_text() or "")
            return
        a = dict(attrs)
        classes = (a.get("class") or "").lower().split()
        if a.get("itemprop") == "description" or self.classes & set(classes):
            self.depth = 1
            self.parts = []

    def handle_startendtag(self, tag, attrs):
        if self.depth:
            self.parts.append(self.get_starttag_text() or "")

    def handle_endtag(self, tag):
        if not self.depth or tag in VOID_TAGS:
            return
        self.depth -= 1
        if self.depth == 0:
            self.blocks.append("".join(self.parts).strip())
        else:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        if self.depth:
            self.parts.append(data)

    def handle_entityref(self, name):
        self.handle_data(f"&{name};")

    def handle_charref(self, name):
        self.handle_data(f"&#{name};")


def extract_description(page_html: str, classes: tuple[str, ...] = ("jobdescription",)) -> str:
    """Description HTML from elements marked itemprop="description" or carrying one
    of `classes`. Also used for other sites with server-rendered job pages."""
    parser = _DescriptionExtractor(classes)
    parser.feed(page_html)
    blocks = []
    for b in parser.blocks:
        if b and b not in blocks:  # skip repeated copies (e.g. mobile + desktop)
            blocks.append(b)
    return "\n".join(blocks)


def page_locations(page_html: str) -> str:
    """All locations listed on a job page, in order, without the page's repeated copies."""
    locs = []
    for fragment in GEO_LOCATION_RE.findall(page_html):
        loc = html_to_text(fragment)
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
            page = self.client.get_text(self._search_url(startrow))
            rows = ROW_RE.findall(page) or [page]
            found = 0
            for row in rows:
                link = JOB_LINK_RE.search(row)
                if not link or link.group(2) in seen:
                    continue
                path, job_id, title = link.groups()
                seen.add(job_id)
                found += 1
                loc = LOCATION_RE.search(row)
                date = DATE_RE.search(row)
                yield JobRef(
                    job_id=job_id,
                    title=unescape(title.strip()),
                    location=html_to_text(MORE_LOCATIONS_RE.sub("", loc.group(1))) if loc else "",
                    url=f"{self.base_url}{unescape(path)}",
                    posted_on=html_to_text(date.group(1)) if date else "",
                )
            total = TOTAL_RE.search(page)
            total = int(re.sub(r"\D", "", total.group(1))) if total else None
            # Advance by what the page actually returned; the site decides the page size
            startrow += len(rows) if rows != [page] else found
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
