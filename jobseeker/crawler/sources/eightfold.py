"""Eightfold career sites, e.g. Microsoft's apply.careers.microsoft.com.

  GET {base_url}/careers?location=<location>
      -> the career site page: sets the visitor cookies (_vs, _vscid) that the API
         expects; without them the search answers HTTP 429 "Please try again later"
  GET {base_url}/api/pcsx/search?domain=<domain>&query=&location=<location>&start=N
      -> data.positions (10 per page) and data.count; each position has `locations`
         ("Switzerland, Zürich, Zürich": country, region, city) and `standardizedLocations`
         ("Zürich, ZH, CH", or just "CH"), postedTs (Unix time) and positionUrl
  GET {base_url}/api/pcsx/position_details?position_id=<id>&domain=<domain>
      -> data.jobDescription (HTML) and facts in efcustomText* fields (work site, travel,
         employment type, ...)

The location search also returns jobs that list Switzerland among other countries, and
may return nearby or remote ones: a job is kept only if one of its standardized locations
is in `country_code`.
"""

from collections.abc import Iterator
from datetime import datetime, timezone
from urllib.parse import urlencode, urljoin

from ..html_text import html_to_text
from .base import JobDetail, JobRef

MAX_PAGES = 20
FACT_PREFIX = "efcustomText"


def iso_date(ts) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).date().isoformat() if ts else ""


def place(location: str) -> str:
    """"Switzerland, Zürich, Zürich" -> "Zürich, Switzerland";
    "Switzerland, Multiple Locations, Multiple Locations" -> "Switzerland"."""
    country, *rest = [p.strip() for p in location.split(",")]
    city = rest[-1] if rest and rest[-1] != "Multiple Locations" else ""
    return f"{city}, {country}" if city else country


def in_country(position: dict, code: str) -> bool:
    return any(loc.split(",")[-1].strip() == code for loc in position.get("standardizedLocations") or [])


def locations_text(locations: list[str], country: str) -> str:
    """The job's places, those in `country` first (the job's place is taken from the first)."""
    return " / ".join(place(loc) for loc in sorted(locations, key=lambda loc: place(loc).split(", ")[-1] != country))


class EightfoldSource:
    def __init__(self, client, base_url: str, domain: str, location: str = "Switzerland",
                 country_code: str = "CH", **_):
        self.client = client
        self.base_url = base_url.rstrip("/")   # e.g. https://apply.careers.microsoft.com
        self.domain = domain                    # Eightfold's tenant, e.g. microsoft.com
        self.location = location
        self.country_code = country_code

    def list_jobs(self) -> Iterator[JobRef]:
        # as a browser does: the career page first, so the API calls carry its cookies
        # (the client keeps them for the run)
        self.client.get_text(f"{self.base_url}/careers?{urlencode({'location': self.location})}")
        start, seen = 0, set()
        for _ in range(MAX_PAGES):
            query = urlencode({"domain": self.domain, "query": "", "location": self.location, "start": start})
            data = self.client.get_json(f"{self.base_url}/api/pcsx/search?{query}")["data"]
            positions = data.get("positions") or []
            for p in positions:
                job_id = str(p["id"])
                if job_id in seen or not in_country(p, self.country_code):
                    continue
                seen.add(job_id)
                yield JobRef(
                    job_id=job_id,
                    title=(p.get("name") or "").strip(),
                    location=locations_text(p.get("locations") or [], self.location),
                    url=urljoin(self.base_url + "/", p.get("positionUrl") or f"careers/job/{job_id}"),
                    posted_on=iso_date(p.get("postedTs")),
                    extra={"display_job_id": p.get("displayJobId"), "department": p.get("department"),
                           "work_location": p.get("workLocationOption")},
                )
            start += len(positions)
            if not positions or start >= data.get("count", 0):
                return
        raise RuntimeError(f"{self.base_url}: more than {MAX_PAGES} pages of results for {self.location}")

    def fetch_detail(self, ref: JobRef) -> JobDetail:
        query = urlencode({"position_id": ref.job_id, "domain": self.domain, "hl": "en"})
        data = self.client.get_json(f"{self.base_url}/api/pcsx/position_details?{query}")["data"]
        html = data.get("jobDescription") or ""
        if not html.strip():
            raise RuntimeError(f"No job description for {ref.job_id} on {self.base_url}")
        facts = {k[len(FACT_PREFIX):]: ", ".join(v) if isinstance(v, list) else v
                 for k, v in data.items() if k.startswith(FACT_PREFIX) and v}
        return JobDetail(
            description_html=html,
            description=html_to_text(html),
            raw={"url": data.get("publicUrl") or ref.url, **ref.extra, "facts": facts},
            title=(data.get("name") or "").strip() or None,
            location=locations_text(data.get("locations") or [], self.location) or None,
            url=data.get("publicUrl") or None,
            posted_on=iso_date(data.get("postedTs")) or None,
        )
