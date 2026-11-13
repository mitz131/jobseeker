"""Johdi Suite, a Swiss applicant tracking system (Piguet Galland).

The employer's careers page calls Johdi's public JSON API; `api_url` is the company's
publication-flow URL from that page (it embeds an opaque company token):

  GET {api_url}/offers/{lang}         -> every open offer: title, city, date (JSON list)
  GET {api_url}/offer/{id}/{lang}     -> one offer, with the full description (JSON)

`job_url` is the employer's own page for an offer, e.g. ".../offre-emploi?offer={id}".
"""

from collections.abc import Iterator

from ..html_text import html_to_text
from .base import JobDetail, JobRef


class JohdiSource:
    def __init__(self, client, api_url: str, job_url: str, lang: str = "fr", **_):
        self.client = client
        self.api_url = api_url.rstrip("/")
        self.job_url = job_url
        self.lang = lang

    def list_jobs(self) -> Iterator[JobRef]:
        offers = self.client.get_json(f"{self.api_url}/offers/{self.lang}")
        if not isinstance(offers, list):
            raise RuntimeError(f"Unexpected Johdi offers response: {str(offers)[:200]}")
        for offer in offers:
            yield JobRef(
                job_id=str(offer["id"]),
                title=(offer.get("title") or "").strip(),
                location=offer.get("city") or offer.get("work_place") or "",
                url=self.job_url.format(id=offer["id"]),
                posted_on=offer.get("publication_date") or "",
            )

    def fetch_detail(self, ref: JobRef) -> JobDetail:
        offer = self.client.get_json(f"{self.api_url}/offer/{ref.job_id}/{self.lang}")
        html = offer.get("description") or ""
        return JobDetail(
            description_html=html,
            description=html_to_text(html),
            raw=offer,
            title=(offer.get("title") or "").strip() or None,
            posted_on=offer.get("publication_date") or None,
        )
