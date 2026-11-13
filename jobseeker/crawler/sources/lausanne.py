"""Ville de Lausanne (the city, not the canton: État de Vaud is the `oracle` source).

The offers page (lausanne.ch/.../nous-rejoindre/offres-emploi.html) fills its list from
the city's search proxy, an Elasticsearch index:

  GET https://www.lausanne.ch/apps/search/proxy-search.php?el_index=emploi
      &fields[]=jobtype&values[]=1 ... &occur=should&size=200   -> every offer (JSON)

Each hit already holds the whole ad (intro, mission, profile, conditions), so there is
no detail request. The hits also carry the city's internal fields (authors, internal
comments, contacts): only the public ones below are kept.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from html import escape
from urllib.parse import urlencode

from ..html_text import html_to_text
from .base import JobDetail, JobRef

API = "https://www.lausanne.ch/apps/search/proxy-search.php"
DETAIL_URL = ("https://www.lausanne.ch/officiel/travailler-a-la-ville/nous-rejoindre/offres-emploi/"
              "detail-offre-emploi/{id}.html")
JOB_TYPES = (1, 2, 3)   # what the offers page asks for; 7 is internships, on another page
PUBLIC_FIELDS = ("title", "label_full", "parent_label", "ville", "nopostal", "ratio_min", "ratio_max",
                 "duration", "cdd", "start_date", "start_tbd", "immediate", "pub_date", "post_date",
                 "ext_data", "mission", "profile", "jobtype", "nb")


def day(timestamp) -> str:
    """The site's dates are local midnight as Unix time (22:00 or 23:00 UTC the day
    before): +12 h lands on the right day in UTC, without a time zone database."""
    if not timestamp:
        return ""
    return datetime.fromtimestamp(int(timestamp) + 12 * 3600, UTC).date().isoformat()


def items(text: str | None) -> list[str]:
    """The ad's lists are plain text, items separated by "$"."""
    return [s.strip() for s in (text or "").split("$") if s.strip()]


def ad_html(job: dict) -> str:
    service = (job.get("label_full") or "").strip()
    parts = [f"<p><strong>{escape(service)}</strong></p>"] if service else []
    parts += [f"<p>{escape(p)}</p>" for p in items(job.get("ext_data"))]
    for heading, field in (("Mission", "mission"), ("Profil", "profile")):
        if entries := items(job.get(field)):
            parts.append(f"<h3>{heading}</h3><ul>" + "".join(f"<li>{escape(e)}</li>" for e in entries) + "</ul>")
    low, high = job.get("ratio_min"), job.get("ratio_max")
    conditions = [f"Taux : {low}%" if low == high or not high else f"Taux : {low}–{high}%"] if low else []
    if job.get("duration"):
        conditions.append(job["duration"].strip())
    start = "dès que possible" if job.get("immediate") else "à convenir" if job.get("start_tbd") else day(job.get("start_date"))
    if start:
        conditions.append(f"Entrée en fonction : {start}")
    if job.get("post_date"):
        conditions.append(f"Délai de postulation : {day(job['post_date'])}")
    if conditions:
        parts.append("<h3>Conditions</h3><ul>" + "".join(f"<li>{escape(c)}</li>" for c in conditions) + "</ul>")
    return "\n".join(parts)


class LausanneSource:
    def __init__(self, client, **_):
        self.client = client
        self._jobs: dict[str, dict] = {}

    def list_jobs(self) -> Iterator[JobRef]:
        query = [("el_index", "emploi")]
        query += [("fields[]", "jobtype") for _ in JOB_TYPES] + [("values[]", t) for t in JOB_TYPES]
        query += [("sortFields[]", "pub_date"), ("sortTypes[]", "desc"), ("occur", "should"), ("size", 500)]
        data = self.client.get_json(f"{API}?{urlencode(query)}")
        hits = (data.get("hits") or {}).get("hits") if isinstance(data, dict) else None
        if hits is None:
            raise RuntimeError(f"Unexpected Lausanne job search response: {str(data)[:200]}")
        self._jobs = {}
        for hit in hits:
            job = {k: hit["_source"].get(k) for k in PUBLIC_FIELDS}
            self._jobs[hit["_id"]] = job
            title = (job.get("title") or "").strip()
            yield JobRef(
                job_id=hit["_id"],
                title=title[:1].upper() + title[1:],   # the site capitalises too
                location=(job.get("ville") or "").strip() or "Lausanne",
                url=DETAIL_URL.format(id=hit["_id"]),
                posted_on=day(job.get("pub_date")),
            )

    def fetch_detail(self, ref: JobRef) -> JobDetail:
        job = self._jobs[ref.job_id]   # the listing already has the ad
        html = ad_html(job)
        return JobDetail(description_html=html, description=html_to_text(html), raw=job)
