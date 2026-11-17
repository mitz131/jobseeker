"""Assura: the health insurer's own careers pages on assura.ch.

assura.ch is a Next.js site whose pages come from a Cockpit CMS. The careers page loads
the job ads in the browser from the CMS's public collection API (no token):

  POST https://cms-blue.assura.ch/api/collections/get/jobAds
       {"lang": "fr", "filter": {"active": true}, "fields": {...}}
       -> {"entries": [...], "total": N}: every active ad, in one response

Each ad has `title`, `slug`, `locations` (list of place names), `region`, `department`,
`type` (employe / stagiaire / apprenti), `rate_min`/`rate_max` and its publish window
(`publishStartDate`, `publishEndDate`, ISO dates). The description is Markdown (with some
raw `<br>`), asked for per new job with the same request filtered by `_id`. The public
page is https://www.assura.ch/fr/carriere/postes-a-pourvoir/<slug>.

Only ads inside their publish window are kept, as on the page. Assura only hires in
Switzerland, so there is no country filter. The site's sitemap lists only a few of the
ads, so it isn't used.
"""

import re
from collections.abc import Iterator
from datetime import date, datetime
from zoneinfo import ZoneInfo

import markdown

from ..html_text import html_to_text
from .base import JobDetail, JobRef

API = "https://cms-blue.assura.ch/api/collections/get/jobAds"
JOB_PAGE = "https://www.assura.ch/fr/carriere/postes-a-pourvoir/"
LIST_FIELDS = ("_id", "title", "slug", "locations", "region", "department", "type",
               "rate_min", "rate_max", "publishStartDate", "publishEndDate")
DETAIL_FIELDS = LIST_FIELDS + ("description", "start_date", "duration", "remote_working")


def swiss_today() -> date:
    return datetime.now(ZoneInfo("Europe/Zurich")).date()


def published(ad: dict, today: date) -> bool:
    """Inside the ad's publish window; a missing or unreadable bound doesn't limit it."""
    def day(key):
        try:
            return date.fromisoformat((ad.get(key) or "")[:10])
        except ValueError:
            return None
    start, end = day("publishStartDate"), day("publishEndDate")
    return (start is None or start <= today) and (end is None or today <= end)


def location(ad: dict) -> str:
    return " / ".join(str(p).strip() for p in ad.get("locations") or [] if str(p).strip())


def markdown_to_html(text: str) -> str:
    """The ads separate list items by blank lines, which Markdown renders as a paragraph
    per item (<li><p>…</p></li>); those are unwrapped, and the line breaks between list
    tags dropped, so the text has one line per item, as for the other sources."""
    html = markdown.markdown(text or "", extensions=["sane_lists"])
    html = re.sub(r"<li>\s*<p>(.*?)</p>\s*</li>", r"<li>\1</li>", html, flags=re.S)
    return re.sub(r"(<[uo]l>|</li>)\s+(?=<li>|</[uo]l>)", r"\1", html)


class AssuraSource:
    def __init__(self, client, **_):
        self.client = client

    def _query(self, filter_: dict, fields: tuple[str, ...]) -> list[dict]:
        data = self.client.post_json(API, {
            "lang": "fr", "filter": {"active": True, **filter_}, "fields": {f: 1 for f in fields},
        })
        if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
            raise RuntimeError(f"Unexpected Assura job list response: {str(data)[:200]}")
        return data["entries"]

    def list_jobs(self, today: date | None = None) -> Iterator[JobRef]:
        today = today or swiss_today()
        for ad in self._query({}, LIST_FIELDS):
            if not isinstance(ad, dict) or not ad.get("_id") or not published(ad, today):
                continue
            yield JobRef(
                job_id=str(ad["_id"]),
                title=(ad.get("title") or "").strip(),
                location=location(ad),
                url=JOB_PAGE + ad["slug"] if ad.get("slug") else "",
                posted_on=(ad.get("publishStartDate") or "")[:10],
            )

    def fetch_detail(self, ref: JobRef) -> JobDetail:
        entries = self._query({"_id": ref.job_id}, DETAIL_FIELDS)
        if not entries:
            raise RuntimeError(f"Assura job {ref.job_id} not found (no longer active?)")
        ad = entries[0]
        html = markdown_to_html(ad.get("description") or "")
        return JobDetail(description_html=html, description=html_to_text(html), raw=ad)
