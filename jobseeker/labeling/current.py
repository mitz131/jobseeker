"""The labels the web API shows, and labelling the jobs that have none yet.

labels.toml [current] names one backend and question set. A job's current labels
are the answers of the newest run of that pair that labelled it, read with the
backend's thresholds; so a full run and the small runs after each crawl add up."""

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from .questions import QuestionSet, load_question_set, load_thresholds
from .runner import INPUT_RECIPES, RunResult, client_for, label_jobs, select_jobs
from .store import LabelStore

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Current:
    backend: str
    questions: QuestionSet
    thresholds: dict[str, float]
    recipe: str


def load_current(labels_config: dict) -> Current | None:
    """labels.toml [current]: backend, questions, input (default full). None if not set."""
    spec = labels_config.get("current")
    if not spec:
        return None
    backend = spec.get("backend")
    if backend not in labels_config.get("backends", {}):
        raise ValueError(f"[current] backend {backend!r} is not defined in labels.toml [backends]")
    qs = load_question_set(labels_config, spec.get("questions", ""))
    recipe = spec.get("input", "full")
    if recipe not in INPUT_RECIPES:
        raise ValueError(f"[current] input {recipe!r} is not one of {', '.join(INPUT_RECIPES)}")
    return Current(backend, qs, load_thresholds(labels_config, backend, qs), recipe)


def current_runs(conn: sqlite3.Connection, current: Current) -> list[int]:
    """Runs of the current backend and question set, oldest first."""
    return [r[0] for r in conn.execute(
        "SELECT id FROM label_runs WHERE backend = ? AND question_set = ? ORDER BY id",
        (current.backend, current.questions.name))]


def current_labels(conn: sqlite3.Connection, current: Current) -> dict[tuple[str, str], dict[str, dict]]:
    """{(company, job_id): {question: {"answer", "probability"}}}; jobs without labels are absent."""
    labels, out = LabelStore(conn), {}
    for run_id in current_runs(conn, current):   # newer runs overwrite older ones
        for key, answers in labels.labels(run_id, current.thresholds).items():
            out[key] = {q: {"answer": a["answer"], "probability": a["probability"]}
                        for q, a in answers.items() if q in current.questions.questions}
    return out


def unlabelled_jobs(conn: sqlite3.Connection, current: Current) -> list[sqlite3.Row]:
    done = current_labels(conn, current)
    return [job for job in select_jobs(conn) if (job["company"], job["job_id"]) not in done]


@dataclass
class LabelOutcome:
    labelled: int = 0
    failed: int = 0
    skipped: str | None = None   # why nothing was sent, e.g. the backend is not running
    run_id: int | None = None


def label_new_jobs(conn: sqlite3.Connection, labels_config: dict,
                   progress: Callable[[int, int], None] | None = None,
                   client=None) -> LabelOutcome:
    """Label the jobs without current labels. A backend that is not reachable is
    not an error: the jobs stay unlabelled until the next refresh."""
    current = load_current(labels_config)
    if current is None:
        return LabelOutcome(skipped="no [current] labels configured")
    jobs = unlabelled_jobs(conn, current)
    if not jobs:
        return LabelOutcome()
    client = client or client_for(labels_config, current.backend)
    if client.model_info() is None:
        return LabelOutcome(skipped=f"{current.backend} is not reachable at {client.url}")
    if progress:
        progress(0, len(jobs))
    result: RunResult = label_jobs(LabelStore(conn), client, current.questions, current.recipe, jobs,
                                   current.backend, "labelled after refresh", progress)
    log.info("Labelled %d new job(s) with %s (run %d, %d failed)",
             result.labeled, current.backend, result.run_id, result.failed)
    return LabelOutcome(result.labeled, result.failed, result.error, result.run_id)
