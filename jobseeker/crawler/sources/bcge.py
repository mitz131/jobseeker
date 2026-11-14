"""Banque Cantonale de Genève (BCGE): the bank's own job portal, jobs.bcge.ch.

The portal is a Next.js app on top of an API Platform back end:

  GET https://jobs.bcge.ch/api/offers   (Accept: application/json)
      -> {"offers": [...], "filters": [...], ...}: every open offer, in one response

Asked for JSON-LD instead, the same URL answers with a broken collection (`totalItems`
wrong, `member` as `[6, [...]]`), so this source relies on the plain JSON. There is no
pagination (a `page` parameter changes nothing). Each offer already holds the whole ad
(`content`, HTML), its public page (`uri`), its publication date (`dateFrom`) and the
facts the page shows as "Place of work", "Activity rate" and "Contract type"
(`information`), so there is no detail request. Offers also carry a few internal fields
(requisition number, reference, category ids): only the ones the public page shows are kept.

Switzerland only: the portal has no country filter and its "Place of work" options include
Dubai and Hong Kong, so offers there are skipped (by the ad's structured country when it
has one, else by the place of work).
"""

import json
import re
from collections.abc import Iterator

from ..html_text import html_to_text
from .base import JobDetail, JobRef

API = "https://jobs.bcge.ch/api/offers"
PUBLIC_FIELDS = ("id", "title", "content", "uri", "dateFrom", "information", "googleJobsJson")
FOREIGN_PLACES = {"dubai", "hong-kong"}   # the portal's non-Swiss "Place of work" options (filterValue)


def facts(offer: dict, key: str = "value") -> dict[str, str]:
    """The page's facts by id (taux-occupation, lieu-travail, type-contrat)."""
    return {i.get("id"): (i.get(key) or "").strip() for i in offer.get("information") or []
            if isinstance(i, dict)}


def address(offer: dict) -> dict:
    """The postal address of the ad's structured data (empty when the offer has none)."""
    try:
        return json.loads(offer.get("googleJobsJson") or "{}")["jobLocation"]["address"] or {}
    except (ValueError, KeyError, TypeError):
        return {}


def location(offer: dict) -> str:
    """The locality of the structured data, else the page's "Place of work"."""
    return (address(offer).get("addressLocality") or "").strip() or facts(offer).get("lieu-travail", "")


def is_swiss(offer: dict) -> bool:
    country = (address(offer).get("addressCountry") or "").strip().upper()
    if country:
        return country == "CH"
    return facts(offer, "filterValue").get("lieu-travail") not in FOREIGN_PLACES


def ad_html(offer: dict) -> str:
    return re.sub(r"^\s*<\?xml[^>]*>", "", offer.get("content") or "").strip()


class BCGESource:
    def __init__(self, client, **_):
        self.client = client
        self._offers: dict[str, dict] = {}

    def list_jobs(self) -> Iterator[JobRef]:
        data = self.client.get_json(API)
        if not isinstance(data, dict) or not isinstance(data.get("offers"), list):
            raise RuntimeError(f"Unexpected BCGE job list response: {str(data)[:200]}")
        self._offers = {}
        for raw in data["offers"]:
            if not is_swiss(raw):
                continue
            offer = {k: raw.get(k) for k in PUBLIC_FIELDS}
            job_id = str(offer["id"])
            self._offers[job_id] = offer
            yield JobRef(
                job_id=job_id,
                title=(offer.get("title") or "").strip(),
                location=location(offer),
                url=offer.get("uri") or "",
                posted_on=(offer.get("dateFrom") or "")[:10],   # local date, as the portal shows it
            )

    def fetch_detail(self, ref: JobRef) -> JobDetail:
        offer = self._offers[ref.job_id]   # the listing already has the ad
        html = ad_html(offer)
        return JobDetail(description_html=html, description=html_to_text(html), raw=offer)
