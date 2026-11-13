"""Crédit Agricole group career portal (groupecreditagricole.jobs, a WordPress site).

The offers pages are rendered server-side, with the filters in the path; the job
cards carry their details as data attributes:

  GET {base}/{locale}/nos-offres/localisations/{location_id}/page/{n}/  -> listing (HTML,
       32 cards per page; pages past the end have none)
  GET {base}/{locale}/nos-offres-emploi/<slug>/   -> detail; the job is embedded as
       schema.org JobPosting JSON-LD

location_id is the site's own location code: 176 is Switzerland (Suisse).
"""

import re
from collections.abc import Iterator
from html import unescape

from bs4 import BeautifulSoup

from ..html_text import html_to_text
from .base import JobDetail, JobRef
from .vaudoise import find_job_posting

DATE_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
STREET_RE = re.compile(r"^.*\d+\s+(?=\D+$)")   # "Route de Saint Julien 7 CAROUGE" -> "CAROUGE"
MAX_PAGES = 50


def iso_date(text: str) -> str:
    """'Mis à jour le 12/11/2026' or '12/11/2026' -> '2026-11-12'; '' if there is no date."""
    m = DATE_RE.search(text or "")
    return f"{m[3]}-{m[2]}-{m[1]}" if m else ""


def clean_location(city: str) -> str:
    """'  Nyon - Suisse' -> 'Nyon, Suisse': the card's place, in the "place, country" form
    used by the other sources. Some cards give a street address: only the town is kept
    ('Chemin de Bérée 38 1010 Lausanne - Suisse' -> 'Lausanne, Suisse')."""
    place, _, country = " ".join(city.split()).rpartition(" - ")
    place = STREET_RE.sub("", place)
    return f"{place}, {country}" if place else country


class CreditAgricoleSource:
    def __init__(self, client, base_url: str, location_id: int, locale: str = "fr", **_):
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.location_id = location_id
        self.locale = locale

    def _page_url(self, page: int) -> str:
        return f"{self.base_url}/{self.locale}/nos-offres/localisations/{self.location_id}/page/{page}/"

    def list_jobs(self) -> Iterator[JobRef]:
        seen, layout_ok = set(), False
        for page in range(1, MAX_PAGES + 1):
            soup = BeautifulSoup(self.client.get_text(self._page_url(page)), "html.parser")
            # the offers page's <main> carries the result count, also when it is 0
            layout_ok = layout_ok or soup.find(attrs={"data-param-total-offers": True}) is not None
            new = 0
            for card in soup.find_all("article", attrs={"data-gtm-jobtitle": True}):
                ref = card.find(attrs={"data-reference": True})
                link = card.select_one(".offer-title a")
                if not ref or not link or ref["data-reference"] in seen:
                    continue
                seen.add(ref["data-reference"])
                new += 1
                yield JobRef(
                    job_id=ref["data-reference"],
                    title=" ".join(card["data-gtm-jobtitle"].split()),
                    location=clean_location(card.get("data-gtm-jobcity", "")),
                    url=link["href"],
                    posted_on=iso_date(card.get("data-gtm-jobpublishdate", "")),
                )
            if not new:
                break
        if not layout_ok:
            raise RuntimeError(f"No jobs found on {self._page_url(1)}; page layout may have changed")

    def fetch_detail(self, ref: JobRef) -> JobDetail:
        job = find_job_posting(self.client.get_text(ref.url))
        html = job.get("description", "")
        return JobDetail(
            description_html=html,
            description=html_to_text(html),
            raw=job,
            title=unescape(job.get("title") or "").strip() or None,
            posted_on=iso_date(job.get("datePosted", "")) or None,
        )
