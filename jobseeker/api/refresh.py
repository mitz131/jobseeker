"""Run the batch in the background when the data is too old, one run at a time.
The batch reports what it is doing (phase, progress) for /api/status."""

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)


def parse_ts(ts: str | None) -> datetime | None:
    return datetime.fromisoformat(ts) if ts else None


class Refresher:
    """`batch` runs the crawl (it opens its own database connection, since it runs
    in another thread); `last_update` returns when the data was last refreshed.
    One process only: the lock doesn't reach across several server workers."""

    def __init__(self, batch: Callable[[], object], last_update: Callable[[], str | None],
                 max_age: timedelta = timedelta(hours=24)):
        self._batch = batch
        self._last_update = last_update
        self.max_age = max_age
        self._lock = threading.Lock()
        self.started_at: str | None = None   # of the current or latest background run
        self.finished_at: str | None = None
        self.error: str | None = None        # if the latest background run crashed
        self.phase: str | None = None        # what the running batch is doing, e.g. "crawling", "labelling"
        self.done: int | None = None         # progress within the phase, if it has a count
        self.total: int | None = None
        self.note: str | None = None         # a remark from the latest run that is not an error

    def report(self, phase: str, done: int | None = None, total: int | None = None):
        """Called by the batch, from its thread."""
        self.phase, self.done, self.total = phase, done, total

    @property
    def running(self) -> bool:
        return self._lock.locked()

    def is_stale(self) -> bool:
        last = parse_ts(self._last_update())
        return last is None or datetime.now(timezone.utc) - last > self.max_age

    def start(self, force: bool = False, batch: Callable[[], object] | None = None) -> tuple[bool, str]:
        """Start a background run unless one is running or the data is fresh. With
        `batch`, run that instead of the crawl (no freshness check), e.g. labelling only."""
        if batch is None and not force and not self.is_stale():
            return False, "data is up to date"
        if not self._lock.acquire(blocking=False):
            return False, "a background job is already running"
        self.started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.finished_at = self.error = self.note = None
        self.phase = self.done = self.total = None
        threading.Thread(target=self._run, args=(batch or self._batch,), name="jobseeker-refresh", daemon=True).start()
        return True, "started"

    def _run(self, batch: Callable[[], object]):
        try:
            batch()
        except Exception as e:  # keep the server alive; report it via /api/status
            log.exception("Background refresh failed")
            self.error = str(e)
        finally:
            self.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self.phase = self.done = self.total = None
            self._lock.release()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until no run is in progress (for tests and shutdown)."""
        if self._lock.acquire(timeout=-1 if timeout is None else timeout):
            self._lock.release()
            return True
        return False
