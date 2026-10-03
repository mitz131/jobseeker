"""Oracle Recruiting Cloud "Candidate Experience" sites (Canton de Vaud).

  GET {host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions
      ?finder=findReqs;siteNumber=..,limit=..,offset=..   -> search (JSON)
  GET {host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails
      ?finder=ById;Id="..",siteNumber=..                  -> detail (JSON)
"""

import urllib.parse
from collections.abc import Iterator

from ..html_text import html_to_text
from .base import JobDetail, JobRef

PAGE_SIZE = 25
# Detail fields that together make up the posting, in the order the site shows them
DESCRIPTION_SECTIONS = [
    ("OrganizationDescriptionStr", None),
    ("ExternalDescriptionStr", None),
    ("ExternalResponsibilitiesStr", "Responsabilités"),
    ("ExternalQualificationsStr", "Profil"),
    ("CorporateDescriptionStr", None),
]


def job_locations(job: dict) -> str:
    """Primary location plus secondary ones. Secondary entries that only name the
    country ("Switzerland") add nothing and are skipped."""
    locs = [job.get("PrimaryLocation")]
    locs += [s.get("Name") for s in job.get("secondaryLocations") or [] if "," in (s.get("Name") or "")]
    seen = []
    for loc in locs:
        if loc and loc not in seen:
            seen.append(loc)
    return " / ".join(seen)


class OracleSource:
    """`sites` may list several career sites of the same employer; a job posted on
    more than one of them is listed once (requisition IDs are shared across sites)."""

    def __init__(self, client, host: str, sites: list[str] | str, lang: str = "fr",
                 public_url: str | None = None, search: str = "", **_):
        self.client = client
        self.api = f"{host.rstrip('/')}/hcmRestApi/resources/latest"
        self.sites = [sites] if isinstance(sites, str) else list(sites)
        # Link shown to people, with {site} filled in; defaults to Oracle's own UI
        self.public_url = (public_url or
                           f"{host.rstrip('/')}/hcmUI/CandidateExperience/{lang}/sites/{{site}}").rstrip("/")
        self.search = search

    def _search_page(self, site: str, offset: int) -> dict:
        finder = f"findReqs;siteNumber={site},limit={PAGE_SIZE},offset={offset},sortBy=POSTING_DATES_DESC"
        if self.search:
            finder += f',keyword="{self.search}"'
        query = urllib.parse.urlencode({"onlyData": "true", "finder": finder,
                                        "expand": "requisitionList.secondaryLocations"},
                                       safe=";,=\"")
        data = self.client.get_json(f"{self.api}/recruitingCEJobRequisitions?{query}")
        return (data.get("items") or [{}])[0]

    def list_jobs(self) -> Iterator[JobRef]:
        seen = set()
        for site in self.sites:
            offset = 0
            while True:
                page = self._search_page(site, offset)
                reqs = page.get("requisitionList") or []
                for r in reqs:
                    if r["Id"] in seen:
                        continue
                    seen.add(r["Id"])
                    yield JobRef(
                        job_id=r["Id"],
                        title=r.get("Title", ""),
                        location=r.get("PrimaryLocation", ""),
                        url=f"{self.public_url.format(site=site)}/job/{r['Id']}",
                        posted_on=r.get("PostedDate", ""),
                        extra={"site": site},
                    )
                offset += PAGE_SIZE
                # `hasMore` is unreliable on this API; page by the reported total instead
                if not reqs or offset >= page.get("TotalJobsCount", 0):
                    break

    def fetch_detail(self, ref: JobRef) -> JobDetail:
        site = ref.extra.get("site", self.sites[0])
        finder = f'ById;Id="{ref.job_id}",siteNumber={site}'
        query = urllib.parse.urlencode({"expand": "all", "onlyData": "true", "finder": finder},
                                       safe=";,=\"")
        data = self.client.get_json(f"{self.api}/recruitingCEJobRequisitionDetails?{query}")
        items = data.get("items") or []
        if not items:
            raise ValueError(f"No detail returned for job {ref.job_id}")
        job = items[0]
        parts = []
        for field, heading in DESCRIPTION_SECTIONS:
            if job.get(field):
                parts.append((f"<h3>{heading}</h3>" if heading else "") + job[field])
        html = "\n".join(parts)
        return JobDetail(
            description_html=html,
            description=html_to_text(html),
            raw=job,
            title=job.get("Title"),
            location=job_locations(job) or None,
            posted_on=job.get("ExternalPostedStartDate", "")[:10] or None,
        )
