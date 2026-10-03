"""Workday career sites (Salesforce, PMI, and many others).

Workday's public career pages are backed by an unauthenticated JSON API:

  POST {base}/wday/cxs/{tenant}/{site}/jobs        -> search (max 20 per page)
  GET  {base}/wday/cxs/{tenant}/{site}{externalPath} -> job detail
"""

import re
from collections.abc import Iterator

from ..html_text import html_to_text
from .base import JobDetail, JobRef

PAGE_SIZE = 20  # Workday rejects larger page sizes


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def iter_facets(nodes: list[dict]) -> Iterator[dict]:
    """Yield every facet, including ones nested inside groups
    (e.g. locationMainGroup -> locationCountry)."""
    for node in nodes:
        if node.get("facetParameter"):
            yield node
        yield from iter_facets([v for v in node.get("values", []) if v.get("values")])


def resolve_facet_filters(facets: list[dict], wanted: dict[str, list[str]]) -> dict[str, list[str]]:
    """Map human-readable filters like {"Country": ["Switzerland"]} to Workday's
    {"locationCountry": ["<id>"]}. Raises if anything can't be matched, so a typo
    never silently turns into an unfiltered fetch."""
    resolved: dict[str, list[str]] = {}
    for key, names in wanted.items():
        k = _norm(key)
        matches = [f for f in iter_facets(facets)
                   if k in (_norm(f["facetParameter"]), _norm(f.get("descriptor")))
                   or _norm(f["facetParameter"]).endswith(k)]
        if len(matches) != 1:
            available = sorted({f"{f['facetParameter']} ({f.get('descriptor', '')})"
                                for f in iter_facets(facets)})
            raise ValueError(f"Facet {key!r} matched {len(matches)} facets; available: "
                             + ", ".join(available))
        facet = matches[0]
        by_name = {_norm(v.get("descriptor")): v["id"]
                   for v in facet.get("values", []) if v.get("id")}
        ids = []
        for name in names:
            if _norm(name) not in by_name:
                raise ValueError(f"No value {name!r} in facet {facet['facetParameter']}; "
                                 "run the `facets` command to see the options")
            ids.append(by_name[_norm(name)])
        resolved.setdefault(facet["facetParameter"], []).extend(ids)
    return resolved


def job_locations(info: dict) -> str:
    """Primary location plus any additional ones; the listing only says "3 Locations"."""
    locs = [info.get("location")] + list(info.get("additionalLocations") or [])
    return " / ".join(loc for loc in locs if loc)


class WorkdaySource:
    def __init__(self, client, base_url: str, tenant: str, site: str, search: str = "",
                 facets: dict | None = None, facet_filters: dict | None = None, **_):
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.site = site
        self.api = f"{self.base_url}/wday/cxs/{tenant}/{site}"
        self.search = search
        self.facets = facets or {}  # raw Workday IDs, used as-is
        self.facet_filters = facet_filters or {}  # names, resolved on each run

    def _search_page(self, offset: int, facets: dict) -> dict:
        return self.client.post_json(f"{self.api}/jobs", {
            "appliedFacets": facets,
            "limit": PAGE_SIZE,
            "offset": offset,
            "searchText": self.search,
        })

    def applied_facets(self) -> dict:
        facets = {k: list(v) for k, v in self.facets.items()}
        if self.facet_filters:
            for k, ids in resolve_facet_filters(self.available_facets(), self.facet_filters).items():
                facets.setdefault(k, []).extend(ids)
        return facets

    def list_jobs(self) -> Iterator[JobRef]:
        facets = self.applied_facets()
        offset, total = 0, None
        while True:
            data = self._search_page(offset, facets)
            postings = data.get("jobPostings") or []
            # Workday only reports an accurate total on the first page.
            if total is None:
                total = data.get("total", 0)
            for p in postings:
                path = p.get("externalPath")
                if not path:
                    continue
                yield JobRef(
                    job_id=path,
                    title=p.get("title", ""),
                    location=p.get("locationsText", ""),
                    url=f"{self.base_url}/en-US/{self.site}{path}",
                    posted_on=p.get("postedOn", ""),
                    extra={"bulletFields": p.get("bulletFields", [])},
                )
            offset += PAGE_SIZE
            if not postings or offset >= total:
                break

    def fetch_detail(self, ref: JobRef) -> JobDetail:
        data = self.client.get_json(f"{self.api}{ref.job_id}")
        info = data.get("jobPostingInfo", {})
        html = info.get("jobDescription", "")
        return JobDetail(
            description_html=html,
            description=html_to_text(html),
            raw=data,
            title=info.get("title"),
            location=job_locations(info) or None,
            url=info.get("externalUrl"),
            posted_on=info.get("startDate") or info.get("postedOn"),
        )

    def available_facets(self) -> list[dict]:
        """Facets (location, category, ...) with the IDs usable in `facets` config."""
        return self._search_page(0, {}).get("facets", [])
