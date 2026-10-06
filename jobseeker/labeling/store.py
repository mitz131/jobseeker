"""Label tables, kept in the same SQLite file as the jobs.

  question_sets  one row per question set ever used, with its full definition
  label_runs     one row per labelling run: who answered (backend, model snapshot),
                 which questions, which input recipe, when, how it went
  job_labels     the answers: (run, company, job_id, question) -> answer + probabilities
"""

import json
import sqlite3

from ..db import now
from .questions import Answer, QuestionSet

SCHEMA = """
CREATE TABLE IF NOT EXISTS question_sets (
    name        TEXT PRIMARY KEY,
    sha         TEXT NOT NULL,
    definition  TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS label_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    backend       TEXT NOT NULL,      -- name in labels.toml, or "claude" / "human" for imports
    endpoint      TEXT,
    model         TEXT,               -- short model id, e.g. "jaredpalmer/kev-4b"
    model_info    TEXT,               -- full snapshot, e.g. the backend's /v1/models answer
    question_set  TEXT NOT NULL REFERENCES question_sets (name),
    input_recipe  TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT NOT NULL,      -- running / done / partial / failed
    labeled       INTEGER NOT NULL DEFAULT 0,
    failed        INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    note          TEXT,
    test          INTEGER NOT NULL DEFAULT 0  -- 1: a trial (speed, settings); never shown as current labels
);

CREATE TABLE IF NOT EXISTS job_labels (
    run_id         INTEGER NOT NULL REFERENCES label_runs (id),
    company        TEXT NOT NULL,
    job_id         TEXT NOT NULL,
    question       TEXT NOT NULL,
    answer         TEXT NOT NULL,
    probability    REAL,              -- of `answer`; NULL when the source gives none
    probabilities  TEXT,              -- JSON, all answers
    raw            TEXT,              -- JSON, the backend's answer as received
    PRIMARY KEY (run_id, company, job_id, question)
);
CREATE INDEX IF NOT EXISTS job_labels_job ON job_labels (company, job_id);
"""


class LabelStore:
    """Works on a JobStore's connection, so jobs and labels share one database."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.executescript(SCHEMA)
        columns = {r[1] for r in self.conn.execute("PRAGMA table_info(label_runs)")}
        if "test" not in columns:   # databases from before test runs
            with self.conn:
                self.conn.execute("ALTER TABLE label_runs ADD COLUMN test INTEGER NOT NULL DEFAULT 0")

    def register_question_set(self, qs: QuestionSet):
        """Store the set on first use; refuse a set edited under a name already used."""
        row = self.conn.execute("SELECT sha FROM question_sets WHERE name = ?", (qs.name,)).fetchone()
        if row is None:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO question_sets (name, sha, definition, created_at) VALUES (?, ?, ?, ?)",
                    (qs.name, qs.sha, json.dumps(qs.definition(), ensure_ascii=False), now()))
        elif row[0] != qs.sha:
            raise ValueError(
                f"Question set {qs.name!r} was changed after it was first used. Labels from the "
                f"old and new wording can't be compared: give the changed set a new name (e.g. v2).")

    def start_run(self, backend: str, endpoint: str | None, model: str | None, model_info,
                  question_set: str, input_recipe: str, note: str | None = None, test: bool = False) -> int:
        with self.conn:
            return self.conn.execute(
                """INSERT INTO label_runs (backend, endpoint, model, model_info, question_set,
                       input_recipe, started_at, status, note, test)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?, ?)""",
                (backend, endpoint, model, json.dumps(model_info, ensure_ascii=False),
                 question_set, input_recipe, now(), note, int(test))).lastrowid

    def add_answers(self, run_id: int, company: str, job_id: str, answers: dict[str, Answer],
                    raw: dict | None = None):
        with self.conn:
            self.conn.executemany(
                """INSERT OR REPLACE INTO job_labels (run_id, company, job_id, question, answer,
                       probability, probabilities, raw) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [(run_id, company, job_id, key, a.answer, a.probability,
                  json.dumps(a.probabilities) if a.probabilities is not None else None,
                  json.dumps((raw or {}).get(key), ensure_ascii=False) if raw else None)
                 for key, a in answers.items()])

    def finish_run(self, run_id: int, labeled: int, failed: int, error: str | None = None):
        status = "failed" if labeled == 0 and (failed or error) else "partial" if failed or error else "done"
        with self.conn:
            self.conn.execute(
                """UPDATE label_runs SET finished_at = ?, status = ?, labeled = ?, failed = ?, error = ?
                   WHERE id = ?""", (now(), status, labeled, failed, error, run_id))

    def runs(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM label_runs ORDER BY id").fetchall()

    def run(self, run_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM label_runs WHERE id = ?", (run_id,)).fetchone()

    def labels(self, run_id: int, thresholds: dict[str, float] | None = None) -> dict[tuple[str, str], dict[str, dict]]:
        """{(company, job_id): {question: row as dict}} for one run.

        With thresholds ({question: p}), a yes/no answer is yes only if p(yes) >= p; the
        stored answer stays as the model gave it and is kept as `stored_answer`."""
        out: dict[tuple[str, str], dict[str, dict]] = {}
        for row in self.conn.execute("SELECT * FROM job_labels WHERE run_id = ?", (run_id,)):
            label = dict(row)
            label["stored_answer"] = label["answer"]
            t = (thresholds or {}).get(label["question"])
            if t is not None and label["probabilities"]:
                p_yes = json.loads(label["probabilities"])["yes"]
                label["answer"] = "yes" if p_yes >= t else "no"
                label["probability"] = p_yes if label["answer"] == "yes" else 1 - p_yes
            out.setdefault((row["company"], row["job_id"]), {})[row["question"]] = label
        return out
