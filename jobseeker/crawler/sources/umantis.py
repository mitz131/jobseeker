"""Umantis (Abacus) career portals, e.g. Bank J. Safra Sarasin's jsafrasarasin.umantis.com.

Everything is server-rendered HTML, no JSON:

  GET {base_url}/Jobs/All
      -> a table with one row per job (tr.tableaslist_contentrow1/2): a link to
         /Vacancies/<id>/Description/<lang>, "Online since: dd.mm.yyyy", then subtitle
         spans "Type: …", "| <department>", "| <city>, CH; <city>, CH"
  GET {base_url}/Vacancies/<id>/Description/<lang>
      -> the ad, in the content boxes of main.page-content

The table carries a "next page" link (data-pagination-next-href) even when every job
fits on the first page; it is followed until a page brings no new job (at most
MAX_PAGES). The row's spans have portal-specific ids, so they are read by their text.
"""

import re
from collections.abc import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ..html_text import html_to_text
from .base import JobDetail, JobRef

MAX_PAGES = 20
JOB_LINK_RE = re.compile(r"/Vacancies/(\d+)/Description\b")
ONLINE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
# the last content box holds the Apply button, links to other jobs and share buttons
NOT_THE_AD = (".apply-btn-box", ".share-container", ".info-list")


def _text(el: Tag | None) -> str:
    return " ".join(el.get_text(" ").split()) if el else ""


def location(text: str) -> str:
    """"| Basel, CH; Zurich, CH" -> "Basel / Zurich"."""
    places = [re.sub(r",\s*CH$", "", p.strip()) for p in text.lstrip("|\xa0 ").split(";")]
    return " / ".join(p for p in places if p)


def iso_date(text: str) -> str:
    m = ONLINE_RE.search(text)
    return f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}" if m else ""


def parse_rows(page_html: str, base_url: str) -> tuple[list[JobRef], str | None]:
    """The page's jobs and the URL of the next page (None if there is none)."""
    soup = BeautifulSoup(page_html, "html.parser")
    refs = []
    for row in soup.find_all("tr", class_=re.compile(r"^tableaslist_contentrow")):
        link = row.find("a", href=JOB_LINK_RE)
        if not link:
            continue
        # subtitles: the title (link), "Type: …", "| department", "| locations"
        subtitles = [_text(s) for s in row.select("span.tableaslist_subtitle")]
        piped = [s for s in subtitles if s.startswith("|")]
        refs.append(JobRef(
            job_id=JOB_LINK_RE.search(link["href"])[1],
            title=_text(link),
            location=location(piped[-1]) if piped else "",
            url=urljoin(base_url, link["href"]),
            posted_on=iso_date(str(row.find(string=re.compile("Online since")) or "")),
            extra={"department": piped[0].lstrip("| ") if len(piped) > 1 else ""},
        ))
    nxt = soup.find(attrs={"data-pagination-next-href": True})
    next_url = urljoin(base_url + "/Jobs/All", nxt["data-pagination-next-href"].split("#")[0]) if nxt else None
    return refs, next_url


def ad_html(page_html: str) -> str:
    soup = BeautifulSoup(page_html, "html.parser")
    main = soup.find("main", class_="page-content")
    if not main:
        raise RuntimeError("No main.page-content on the job page; page layout may have changed")
    for el in main.select(", ".join(NOT_THE_AD)):
        el.decompose()
    # the page is indented HTML: line breaks between tags are layout, not text (else each
    # list item would come out as "-" followed by its text two lines down)
    for blank in main.find_all(string=re.compile(r"^\s*\n\s*$")):
        blank.extract()
    boxes = main.find_all("div", class_="content-box", recursive=False) or [main]
    return "\n".join(str(b) for b in boxes if b.get_text(strip=True))


class UmantisSource:
    def __init__(self, client, base_url: str, **_):
        self.client = client
        self.base_url = base_url.rstrip("/")

    def list_jobs(self) -> Iterator[JobRef]:
        url, seen = f"{self.base_url}/Jobs/All", set()
        for _ in range(MAX_PAGES):
            refs, url = parse_rows(self.client.get_text(url), self.base_url)
            new = [r for r in refs if r.job_id not in seen]
            seen.update(r.job_id for r in new)
            yield from new
            if not new or not url:
                break
        if not seen:
            raise RuntimeError(f"No jobs found on {self.base_url}/Jobs/All; page layout may have changed")

    def fetch_detail(self, ref: JobRef) -> JobDetail:
        html = ad_html(self.client.get_text(ref.url))
        return JobDetail(description_html=html, description=html_to_text(html), raw={"url": ref.url, **ref.extra})
