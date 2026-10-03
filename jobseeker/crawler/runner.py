"""Daily run: list jobs per company, diff against the DB, fetch details for new ones."""

import logging
import re
from dataclasses import dataclass

from ..db import JobStore, now
from .sources import build_source
from .sources.base import JobRef

log = logging.getLogger(__name__)


def _matches_any(text: str, words: list[str]) -> bool:
    """Whole-word, case-insensitive, allowing plural/feminine endings (-e, -s, -es):
    "apprenti" matches "Apprenties ou apprentis", "intern" matches "Interns",
    but "intern" does not match "Internal"."""
    return any(re.search(rf"\b{re.escape(w)}(?:e|s|es)?\b", text, re.I) for w in words)


def passes_filter(ref: JobRef, flt: dict) -> bool:
    """Client-side filter applied on top of the site's own search."""
    if flt.get("title_include") and not _matches_any(ref.title, flt["title_include"]):
        return False
    if flt.get("title_exclude") and _matches_any(ref.title, flt["title_exclude"]):
        return False
    if flt.get("location_include") and not _matches_any(ref.location, flt["location_include"]):
        return False
    return True


@dataclass
class CompanyResult:
    company: str
    listed: int = 0
    new: int = 0
    error: str | None = None


def run_company(store: JobStore, client, company: dict, max_new: int) -> CompanyResult:
    name = company["name"]
    result = CompanyResult(name)
    run_id = store.start_run(name)
    try:
        source = build_source(client, company)
        refs = [r for r in source.list_jobs() if passes_filter(r, company.get("filter", {}))]
        result.listed = len(refs)

        ts = now()
        known = store.known_ids(name)
        store.mark_seen(name, [r.job_id for r in refs if r.job_id in known], ts)
        new_refs = [r for r in refs if r.job_id not in known]
        if len(new_refs) > max_new:
            log.warning("%s: %d new jobs, fetching first %d (rest on next run)",
                        name, len(new_refs), max_new)
            new_refs = new_refs[:max_new]

        for ref in new_refs:
            try:
                detail = source.fetch_detail(ref)
            except Exception as e:  # one bad posting shouldn't sink the run
                log.warning("%s: failed to fetch %s: %s", name, ref.job_id, e)
                continue
            store.add_job(name, ref, detail, ts)
            result.new += 1
            log.info("%s: NEW %s | %s", name, ref.title, ref.location)
    except Exception as e:
        log.exception("%s: run failed", name)
        result.error = str(e)
    store.finish_run(run_id, result.listed, result.new, result.error)
    return result
