"""One labelling run: send each job to a /v1/systemone backend and store the answers.
Also: importing answers given without a backend (Claude or human labels)."""

import logging
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import requests

from .questions import Answer, QuestionSet, parse_answer, plain_answer
from .store import LabelStore

log = logging.getLogger(__name__)

# What the model gets to read. The recipe is stored with each run, since it
# changes the answers as much as the model does. Only the full text: requirements
# such as languages usually come at the end of an ad, so a shortened text misses them.
INPUT_RECIPES: dict[str, Callable[[sqlite3.Row], str]] = {
    "full": lambda job: (f"Job title: {job['title']}\nLocation: {job['location']}\n\n"
                         f"{job['description'] or ''}"),
}
# Stop early if this many jobs in a row fail at the start: the backend is most likely down
GIVE_UP_AFTER = 5


class SystemOneClient:
    """KEV's own server, llama.cpp / llama.app, or the Jev API: they share this API."""

    def __init__(self, url: str, model: str, api_key: str | None = None, timeout: float = 120):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.session = requests.Session()
        if api_key:
            self.session.headers["Authorization"] = f"Bearer {api_key}"

    def model_info(self) -> dict | None:
        """The backend's description of the model it serves, kept with the run."""
        try:
            resp = self.session.get(f"{self.url}/v1/models", timeout=self.timeout)
            return resp.json() if resp.ok else None
        except (requests.RequestException, ValueError):
            return None

    def ask(self, state: str, questions: dict) -> dict:
        """The `answers` part of the response: {question key: raw answer}."""
        resp = self.session.post(f"{self.url}/v1/systemone", timeout=self.timeout,
                                 json={"state": state, "model": self.model, "questions": questions})
        if not resp.ok:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json()["answers"]


def model_id(info: dict | None, fallback: str) -> str:
    """Short model id from a /v1/models answer, e.g. KEV's "jaredpalmer/kev-4b"."""
    models = (info or {}).get("models") or (info or {}).get("data") or []
    first = models[0] if models and isinstance(models[0], dict) else {}
    return first.get("run") or first.get("id") or first.get("name") or fallback


def select_jobs(conn: sqlite3.Connection, companies: list[str] | None = None,
                keys: Iterable[tuple[str, str]] | None = None, limit: int | None = None) -> list[sqlite3.Row]:
    rows = conn.execute("""SELECT company, job_id, title, location, description FROM jobs
                           ORDER BY first_seen DESC, company, job_id""").fetchall()
    if companies:
        rows = [r for r in rows if r["company"] in companies]
    if keys is not None:
        wanted = set(keys)
        rows = [r for r in rows if (r["company"], r["job_id"]) in wanted]
    return rows[:limit] if limit else rows


@dataclass
class RunResult:
    run_id: int
    labeled: int
    failed: int
    error: str | None


def label_jobs(labels: LabelStore, client: SystemOneClient, qs: QuestionSet, recipe: str,
               jobs: list[sqlite3.Row], backend: str, note: str | None = None,
               progress: Callable[[int, int], None] | None = None) -> RunResult:
    if recipe not in INPUT_RECIPES:
        raise ValueError(f"Unknown input recipe {recipe!r}; known: {', '.join(INPUT_RECIPES)}")
    labels.register_question_set(qs)
    info = client.model_info()
    run_id = labels.start_run(backend, client.url, model_id(info, client.model), info,
                              qs.name, recipe, note)
    questions, build_state = qs.systemone_questions(), INPUT_RECIPES[recipe]
    labeled = failed = 0
    error = None
    for i, job in enumerate(jobs, 1):
        try:
            raw = client.ask(build_state(job), questions)
            answers = {key: parse_answer(q, raw[key]) for key, q in qs.questions.items()}
        except Exception as e:  # one bad answer shouldn't end the run
            failed += 1
            log.warning("%s/%s: %s", job["company"], job["job_id"], e)
            if labeled == 0 and failed >= GIVE_UP_AFTER:
                error = f"gave up after {failed} failures in a row: {e}"
                break
            continue
        labels.add_answers(run_id, job["company"], job["job_id"], answers, raw)
        labeled += 1
        if progress:
            progress(i, len(jobs))
    labels.finish_run(run_id, labeled, failed, error)
    return RunResult(run_id, labeled, failed, error)


def import_labels(labels: LabelStore, conn: sqlite3.Connection, qs: QuestionSet, items: list[dict],
                  backend: str, model: str, recipe: str, note: str | None = None) -> RunResult:
    """Answers without probabilities, e.g. from Claude or a person:
    [{"company": ..., "job_id": ..., "answers": {"seniority": "senior", "computer_engineering": "yes", ...}}]
    Questions missing from an item are left unanswered for that job."""
    labels.register_question_set(qs)
    known = {(r["company"], r["job_id"]) for r in conn.execute("SELECT company, job_id FROM jobs")}
    run_id = labels.start_run(backend, None, model, {"source": "import", "model": model},
                              qs.name, recipe, note)
    labeled = failed = 0
    for item in items:
        key = (item["company"], item["job_id"])
        try:
            if key not in known:
                raise ValueError("no such job")
            unknown = set(item["answers"]) - set(qs.questions)
            if unknown:
                raise ValueError(f"questions not in {qs.name}: {', '.join(sorted(unknown))}")
            answers: dict[str, Answer] = {q: plain_answer(qs.questions[q], v) for q, v in item["answers"].items()}
        except (ValueError, KeyError) as e:
            failed += 1
            log.warning("%s/%s: %s", *key, e)
            continue
        labels.add_answers(run_id, *key, answers)
        labeled += 1
    labels.finish_run(run_id, labeled, failed)
    return RunResult(run_id, labeled, failed, None)
