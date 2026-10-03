"""SQLite storage. (company, job_id) is the key used to diff against earlier runs."""

import json
import sqlite3
from datetime import datetime, timezone

from .crawler.sources.base import JobDetail, JobRef

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    company          TEXT NOT NULL,
    job_id           TEXT NOT NULL,
    title            TEXT,
    location         TEXT,
    url              TEXT,
    posted_on        TEXT,
    description      TEXT,
    description_html TEXT,
    raw_json         TEXT,
    first_seen       TEXT NOT NULL,
    last_seen        TEXT NOT NULL,
    PRIMARY KEY (company, job_id)
);
CREATE INDEX IF NOT EXISTS jobs_first_seen ON jobs (first_seen);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company     TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    listed      INTEGER,
    new         INTEGER,
    error       TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobStore:
    def __init__(self, path: str):
        try:
            self.conn = self._open(path)
        except sqlite3.OperationalError:
            # Some mounted filesystems (FUSE/NTFS, network shares) don't support
            # POSIX locks; lock files work there and suffice for a single writer.
            self.conn = self._open(f"file:{path}?vfs=unix-dotfile", uri=True)

    @staticmethod
    def _open(target: str, uri: bool = False) -> sqlite3.Connection:
        # A reader (the web API) may meet the background batch mid-write: wait for it
        conn = sqlite3.connect(target, uri=uri, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        return conn

    def close(self):
        self.conn.close()

    def known_ids(self, company: str) -> set[str]:
        rows = self.conn.execute("SELECT job_id FROM jobs WHERE company = ?", (company,))
        return {r[0] for r in rows}

    def mark_seen(self, company: str, job_ids: list[str], ts: str):
        with self.conn:
            self.conn.executemany(
                "UPDATE jobs SET last_seen = ? WHERE company = ? AND job_id = ?",
                [(ts, company, j) for j in job_ids],
            )

    def add_job(self, company: str, ref: JobRef, detail: JobDetail, ts: str):
        with self.conn:
            self.conn.execute(
                """INSERT OR IGNORE INTO jobs (company, job_id, title, location, url, posted_on,
                       description, description_html, raw_json, first_seen, last_seen)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (company, ref.job_id, detail.title or ref.title, detail.location or ref.location,
                 detail.url or ref.url, detail.posted_on or ref.posted_on, detail.description,
                 detail.description_html, json.dumps(detail.raw), ts, ts),
            )

    def start_run(self, company: str) -> int:
        with self.conn:
            return self.conn.execute(
                "INSERT INTO runs (company, started_at) VALUES (?, ?)", (company, now())
            ).lastrowid

    def finish_run(self, run_id: int, listed: int, new: int, error: str | None = None):
        with self.conn:
            self.conn.execute(
                "UPDATE runs SET finished_at = ?, listed = ?, new = ?, error = ? WHERE id = ?",
                (now(), listed, new, error, run_id),
            )

    def jobs_since(self, since: str, company: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM jobs WHERE first_seen >= ?"
        args: list = [since]
        if company:
            sql += " AND company = ?"
            args.append(company)
        return self.conn.execute(sql + " ORDER BY first_seen DESC, company", args).fetchall()

    def all_jobs(self) -> list[sqlite3.Row]:
        """Every stored job, without the bulky description, HTML and raw payload."""
        return self.conn.execute(
            """SELECT company, job_id, title, location, url, posted_on, first_seen, last_seen
               FROM jobs ORDER BY first_seen DESC, company, title""").fetchall()

    def get_job(self, company: str, job_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM jobs WHERE company = ? AND job_id = ?",
                                 (company, job_id)).fetchone()

    def last_good_run_starts(self) -> dict[str, str]:
        """Start of each company's latest successful run. A job seen in that run
        (last_seen >= its start) is still open."""
        rows = self.conn.execute(
            """SELECT company, MAX(started_at) FROM runs
               WHERE finished_at IS NOT NULL AND error IS NULL GROUP BY company""")
        return {company: started for company, started in rows}

    def latest_runs(self) -> list[sqlite3.Row]:
        """Each company's most recent run, successful or not."""
        return self.conn.execute(
            """SELECT r.* FROM runs r
               JOIN (SELECT company, MAX(id) AS id FROM runs GROUP BY company) last USING (id)
               ORDER BY r.company""").fetchall()

    def last_update(self) -> str | None:
        """When the most recent successful company run finished."""
        return self.conn.execute(
            "SELECT MAX(finished_at) FROM runs WHERE error IS NULL").fetchone()[0]
