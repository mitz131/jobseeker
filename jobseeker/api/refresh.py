"""Run the batch in the background when the data is too old, one run at a time."""

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

    @property
    def running(self) -> bool:
        return self._lock.locked()

    def is_stale(self) -> bool:
        last = parse_ts(self._last_update())
        return last is None or datetime.now(timezone.utc) - last > self.max_age

    def start(self, force: bool = False) -> tuple[bool, str]:
        """Start a background run unless one is running or the data is fresh."""
        if not force and not self.is_stale():
            return False, "data is up to date"
        if not self._lock.acquire(blocking=False):
            return False, "a refresh is already running"
        self.started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.finished_at = self.error = None
        threading.Thread(target=self._run, name="jobseeker-refresh", daemon=True).start()
        return True, "refresh started"

    def _run(self):
        try:
            self._batch()
        except Exception as e:  # keep the server alive; report it via /api/status
            log.exception("Background refresh failed")
            self.error = str(e)
        finally:
            self.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self._lock.release()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until no run is in progress (for tests and shutdown)."""
        if self._lock.acquire(timeout=-1 if timeout is None else timeout):
            self._lock.release()
            return True
        return False
