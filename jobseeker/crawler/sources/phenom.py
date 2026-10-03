"""Phenom People career sites (Philip Morris: join.pmicareers.com).

  POST {base}/widgets  {"ddoKey": "refineSearch", ...}  -> search (JSON)
  GET  {base}/{locale_path}/job/{jobId}                 -> detail page; the job
       JSON is embedded in the page as `phApp.ddo = {...};`
"""

import json
import re
from collections.abc import Iterator

from ..html_text import html_to_text
from .base import JobDetail, JobRef

DDO_RE = re.compile(r"phApp\.ddo\s*=\s*(\{.*?\});\s*phApp\.", re.S)
# Search-index / ML fields that bloat the stored payload without adding information
NOISE_PREFIXES = ("completeDescription_chunk_", "emb_", "ml_")


def parse_ddo(page_html: str) -> dict:
    m = DDO_RE.search(page_html)
    if not m:
        raise ValueError("phApp.ddo not found in page")
    return json.loads(m.group(1))


def job_locations(job: dict) -> list[str]:
    """All locations of a job; the plain `location` field only holds the first."""
    locs = [loc if isinstance(loc, str) else loc.get("location", "")
            for loc in job.get("multi_location") or []]
    return [loc for loc in locs if loc] or [job.get("location", "")]


class PhenomSource:
    def __init__(self, client, base_url: str, locale_path: str = "gb/en", lang: str = "en_gb",
                 site_country: str = "gb", page_id: str = "page15", search: str = "",
                 selected_fields: dict | None = None, page_size: int = 10, **_):
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.locale_path = locale_path.strip("/")
        self.lang = lang
        self.site_country = site_country
        self.page_id = page_id
        self.search = search
        self.selected_fields = selected_fields or {}
        self.page_size = page_size

    def _search_page(self, offset: int) -> dict:
        data = self.client.post_json(f"{self.base_url}/widgets", {
            "lang": self.lang, "deviceType": "desktop", "country": self.site_country,
            "pageName": "search-results", "ddoKey": "refineSearch", "pageId": self.page_id,
            "siteType": "external", "jdsource": "facets", "global": True,
            "jobs": True, "counts": True, "all_fields": list(self.selected_fields),
            "keywords": self.search, "selected_fields": self.selected_fields,
            "from": offset, "size": self.page_size,
        })
        result = data.get("refineSearch", {})
        if result.get("status") != 200:
            raise RuntimeError(f"Phenom search failed: {json.dumps(result)[:300]}")
        return result

    def list_jobs(self) -> Iterator[JobRef]:
        offset, seen = 0, set()
        while True:
            result = self._search_page(offset)
            jobs = result.get("data", {}).get("jobs", [])
            for j in jobs:
                if j["jobId"] in seen:
                    continue
                seen.add(j["jobId"])
                yield JobRef(
                    job_id=j["jobId"],
                    title=j.get("title", ""),
                    location=" / ".join(job_locations(j)),
                    url=f"{self.base_url}/{self.locale_path}/job/{j['jobId']}",
                    posted_on=(j.get("postedDate") or "")[:10],
                )
            offset += self.page_size
            if not jobs or offset >= result.get("totalHits", 0):
                break

    def fetch_detail(self, ref: JobRef) -> JobDetail:
        ddo = parse_ddo(self.client.get_text(ref.url))
        job = ddo.get("jobDetail", {}).get("data", {}).get("job", {})
        if not job:
            raise ValueError(f"No job data on {ref.url}")
        html = job.get("description", "")
        return JobDetail(
            description_html=html,
            description=html_to_text(html),
            raw={k: v for k, v in job.items() if not k.startswith(NOISE_PREFIXES)},
            title=job.get("title"),
            location=" / ".join(job_locations(job)),
            posted_on=(job.get("postedDate") or "")[:10] or None,
        )
