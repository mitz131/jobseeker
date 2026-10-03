"""FastAPI app: browse stored jobs, filter by distance, refresh in the background.

Interactive documentation is served at /docs (Swagger UI) and /redoc.
"""

from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel

from ..config import Config
from ..crawler.http import HttpClient
from ..crawler.runner import run_all
from ..db import JobStore
from ..places import distance_to_job, norm
from .refresh import Refresher


class JobSummary(BaseModel):
    company: str
    job_id: str
    title: str | None
    location: str | None
    url: str | None
    posted_on: str | None
    first_seen: str
    last_seen: str
    open: bool  # seen in the company's latest successful run
    distance_km: float | None = None  # only when `home` is given and the location is known
    nearest: str | None = None  # the location the distance was measured to


class JobList(BaseModel):
    total: int  # matching jobs, before limit/offset
    home: str | None  # the resolved starting point, e.g. "Renens VD (VD)"
    items: list[JobSummary]


class Job(JobSummary):
    description: str | None


class CompanyStatus(BaseModel):
    company: str
    last_run_finished: str | None
    listed: int | None
    new: int | None
    error: str | None


class Status(BaseModel):
    last_update: str | None  # latest successful company run
    stale: bool  # older than the refresh threshold
    max_age_hours: float
    refresh_running: bool
    refresh_started_at: str | None
    refresh_finished_at: str | None
    refresh_error: str | None
    companies: list[CompanyStatus]


class RefreshResult(BaseModel):
    started: bool
    reason: str


def create_app(config: Config, batch: Callable[[], object] | None = None,
               max_age: timedelta = timedelta(hours=24)) -> FastAPI:
    """`batch` defaults to crawling every enabled company; tests pass a fake."""

    def store() -> Iterator[JobStore]:
        # One connection per request: FastAPI serves requests from a thread pool
        s = JobStore(str(config.db_path))
        try:
            yield s
        finally:
            s.close()

    def crawl():
        s = JobStore(str(config.db_path))
        try:
            run_all(s, HttpClient(delay=config.request_delay), config.companies(),
                    config.max_new_per_company)
        finally:
            s.close()

    def last_update() -> str | None:
        s = JobStore(str(config.db_path))
        try:
            return s.last_update()
        finally:
            s.close()

    refresher = Refresher(batch or crawl, last_update, max_age)
    app = FastAPI(title="jobseeker", version="0.1.0",
                  description="Swiss job openings from employer career sites, "
                              "with straight-line distance search.")
    app.state.refresher = refresher
    Store = Annotated[JobStore, Depends(store)]

    def summary(row, open_since: dict[str, str]) -> dict:
        started = open_since.get(row["company"])
        return {k: row[k] for k in JobSummary.model_fields if k in row.keys()} | {
            "open": started is None or row["last_seen"] >= started}

    @app.get("/api/jobs", response_model=JobList, summary="List stored jobs")
    def list_jobs(
        db: Store,
        home: Annotated[str | None, Query(description='Starting point: postcode ("1020") or locality ("Renens VD")')] = None,
        max_km: Annotated[float | None, Query(ge=0, description="Only jobs within this distance of `home`")] = None,
        company: Annotated[list[str] | None, Query(description="Only these companies (repeatable)")] = None,
        location: Annotated[str | None, Query(description="Text in the location, ignoring case and accents")] = None,
        include_closed: Annotated[bool, Query(description="Also jobs no longer listed by the employer")] = False,
        sort: Annotated[Literal["date", "distance"], Query(description="date: newest first; distance: nearest first")] = "date",
        limit: Annotated[int, Query(ge=1, le=1000)] = 200,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> JobList:
        if (max_km is not None or sort == "distance") and not home:
            raise HTTPException(400, "`max_km` and sort=distance need `home`")
        home_place = None
        if home:
            if not config.places:
                raise HTTPException(503, "Distance search unavailable: locality register not found")
            try:
                home_place = config.places.resolve_home(home)
            except ValueError as e:
                raise HTTPException(400, str(e))

        open_since = db.last_good_run_starts()
        wanted_location = norm(location) if location else None
        items = []
        for row in db.all_jobs():
            item = summary(row, open_since)
            if not include_closed and not item["open"]:
                continue
            if company and row["company"] not in company:
                continue
            if wanted_location and wanted_location not in norm(row["location"] or ""):
                continue
            if home_place:
                match = distance_to_job(config.places, home_place, row["location"])
                if match:
                    item |= {"distance_km": round(match.km, 1), "nearest": match.label}
                if max_km is not None and (match is None or match.km > max_km):
                    continue
            items.append(item)

        if sort == "distance":  # unknown locations last; all_jobs() is newest first already
            items.sort(key=lambda i: (i.get("distance_km") is None, i.get("distance_km") or 0))
        return JobList(total=len(items),
                       home=f"{home_place.name} ({home_place.canton})" if home_place else None,
                       items=items[offset:offset + limit])

    @app.get("/api/jobs/{company}/{job_id:path}", response_model=Job, summary="One job, with description")
    def get_job(company: str, job_id: str, db: Store) -> Job:
        # job_id may contain slashes (Workday ids are paths), hence :path
        row = db.get_job(company, job_id)
        if row is None:
            raise HTTPException(404, "Job not found")
        return Job(**summary(row, db.last_good_run_starts()), description=row["description"])

    @app.get("/api/status", response_model=Status, summary="Data age and refresh state")
    def status(db: Store) -> Status:
        return Status(
            last_update=db.last_update(),
            stale=refresher.is_stale(),
            max_age_hours=refresher.max_age.total_seconds() / 3600,
            refresh_running=refresher.running,
            refresh_started_at=refresher.started_at,
            refresh_finished_at=refresher.finished_at,
            refresh_error=refresher.error,
            companies=[CompanyStatus(company=r["company"], last_run_finished=r["finished_at"],
                                     listed=r["listed"], new=r["new"], error=r["error"])
                       for r in db.latest_runs()],
        )

    @app.post("/api/refresh", response_model=RefreshResult, summary="Start the batch in the background")
    def refresh(force: Annotated[bool, Query(description="Run even if the data is up to date")] = False) -> RefreshResult:
        """Starts a run if the data is older than the threshold (24 h), unless one is
        already running. Returns immediately; poll /api/status for progress."""
        started, reason = refresher.start(force=force)
        return RefreshResult(started=started, reason=reason)

    return app
