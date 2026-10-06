"""FastAPI app: browse stored jobs, filter by distance and by labels, refresh in the
background (crawl, then label the new jobs).

Interactive documentation is served at /docs (Swagger UI) and /redoc; the web
page (frontend/src) at /.
"""

from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import Config
from ..crawler.http import HttpClient
from ..crawler.runner import run_all
from ..db import JobStore
from ..labeling.current import current_labels, label_new_jobs, load_current
from ..places import distance_to_job, norm
from .refresh import Refresher

# The repository's frontend/src (jobseeker/api/app.py -> repository root)
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend" / "src"


class Label(BaseModel):
    answer: str
    probability: float | None  # of `answer`; None for labels without probabilities


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
    labels: dict[str, Label] | None = None  # question -> answer; None: not labelled yet


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
    refresh_phase: str | None = None  # "crawling" or "labelling" while running
    refresh_done: int | None = None   # labelling progress
    refresh_total: int | None = None
    refresh_note: str | None = None   # e.g. why labelling was skipped
    unlabelled: int | None = None     # stored jobs without current labels; None: labels not configured
    companies: list[CompanyStatus]


class LabelOption(BaseModel):
    key: str
    description: str


class LabelQuestion(BaseModel):
    key: str
    type: Literal["choice", "noul"]
    instructions: str
    options: list[LabelOption]  # yes/no questions: yes and no


class LabelInfo(BaseModel):
    backend: str
    question_set: str
    thresholds: dict[str, float]
    questions: list[LabelQuestion]


class RefreshResult(BaseModel):
    started: bool
    reason: str


def create_app(config: Config, batch: Callable[[], object] | None = None,
               max_age: timedelta = timedelta(hours=24),
               frontend_dir: Path | None = FRONTEND_DIR, label_client=None) -> FastAPI:
    """`batch` defaults to crawling every enabled company, then labelling the new jobs;
    tests pass a fake. `frontend_dir` is served at / (None: API only). `label_client`
    replaces the labels.toml backend (tests)."""

    def store() -> Iterator[JobStore]:
        # One connection per request: FastAPI serves requests from a thread pool
        s = JobStore(str(config.db_path))
        try:
            yield s
        finally:
            s.close()

    current = load_current(config.labels)

    def label_new():
        refresher.report("labelling")
        s = JobStore(str(config.db_path))
        try:
            outcome = label_new_jobs(s.conn, config.labels, lambda i, n: refresher.report("labelling", i, n),
                                     client=label_client)
        finally:
            s.close()
        if outcome.skipped:
            refresher.note = f"Labelling skipped: {outcome.skipped}"
        elif outcome.failed:
            refresher.note = f"Labelled {outcome.labelled} job(s), {outcome.failed} failed"

    def crawl():
        refresher.report("crawling")
        s = JobStore(str(config.db_path))
        try:
            run_all(s, HttpClient(delay=config.request_delay), config.companies(),
                    config.max_new_per_company)
        finally:
            s.close()
        label_new()

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

    def label_filter(values: list[str]) -> dict[str, set[str]]:
        """["question:answer", ...] -> {question: {answers}}; 400 for unknown ones."""
        if values and current is None:
            raise HTTPException(400, "Labels are not configured (labels.toml [current])")
        wanted: dict[str, set[str]] = {}
        for v in values:
            q, _, a = v.partition(":")
            question = current.questions.questions.get(q)
            if question is None:
                raise HTTPException(400, f"Unknown label question {q!r}")
            if a not in question.answers():
                raise HTTPException(400, f"{q}: {a!r} is not one of {', '.join(question.answers())}")
            wanted.setdefault(q, set()).add(a)
        return wanted

    @app.get("/api/jobs", response_model=JobList, summary="List stored jobs")
    def list_jobs(
        db: Store,
        home: Annotated[str | None, Query(description='Starting point: postcode ("1020") or locality ("Renens VD")')] = None,
        max_km: Annotated[float | None, Query(ge=0, description="Only jobs within this distance of `home`")] = None,
        company: Annotated[list[str] | None, Query(description="Only these companies (repeatable)")] = None,
        location: Annotated[str | None, Query(description="Text in the location, ignoring case and accents")] = None,
        include_closed: Annotated[bool, Query(description="Also jobs no longer listed by the employer")] = False,
        sort: Annotated[Literal["date", "distance"], Query(description="date: newest first; distance: nearest first")] = "date",
        label: Annotated[list[str] | None, Query(
            description='Label filters "question:answer", e.g. "job_family:software_it" (repeatable). '
                        "Answers of one question are alternatives, several questions must all match. "
                        "Jobs not labelled yet are always included. See /api/labels.")] = None,
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

        wanted_labels = label_filter(label or [])
        labels = current_labels(db.conn, current) if current else {}
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
            job_labels = labels.get((row["company"], row["job_id"]))
            if job_labels is not None:
                if any(job_labels.get(q, {}).get("answer") not in answers for q, answers in wanted_labels.items()):
                    continue
                item["labels"] = job_labels
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
        labels = current_labels(db.conn, current).get((company, job_id)) if current else None
        return Job(**summary(row, db.last_good_run_starts()), labels=labels, description=row["description"])

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
            refresh_phase=refresher.phase,
            refresh_done=refresher.done,
            refresh_total=refresher.total,
            refresh_note=refresher.note,
            unlabelled=(db.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
                        - len(current_labels(db.conn, current))) if current else None,
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

    @app.get("/api/labels", response_model=LabelInfo, summary="The label questions and their answers")
    def label_info() -> LabelInfo:
        """What /api/jobs `labels` and the `label` filter use: labels.toml [current]."""
        if current is None:
            raise HTTPException(404, "Labels are not configured (labels.toml [current])")
        questions = []
        for key, q in current.questions.questions.items():
            options = q.options if q.type == "choice" else {"yes": "yes", "no": "no"}
            questions.append(LabelQuestion(key=key, type=q.type, instructions=q.instructions,
                                           options=[LabelOption(key=k, description=d) for k, d in options.items()]))
        return LabelInfo(backend=current.backend, question_set=current.questions.name,
                         thresholds=current.thresholds, questions=questions)

    @app.post("/api/label", response_model=RefreshResult, summary="Label the jobs that have no labels yet")
    def label_now() -> RefreshResult:
        """Starts labelling in the background (also part of every refresh), unless a
        background job is running. Returns immediately; poll /api/status for progress."""
        if current is None:
            raise HTTPException(404, "Labels are not configured (labels.toml [current])")
        started, reason = refresher.start(batch=label_new)
        return RefreshResult(started=started, reason=reason)

    # Mounted last, so the API routes and /docs take precedence over files
    if frontend_dir and frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    return app
