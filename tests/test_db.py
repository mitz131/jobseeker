import threading

from jobseeker.db import JobStore


def test_connection_can_be_used_from_another_thread(tmp_path):
    # FastAPI may open a request's connection on one worker thread and run the
    # endpoint on another; sqlite3 refuses that unless check_same_thread=False
    store = JobStore(str(tmp_path / "jobs.db"))
    errors = []

    def use():
        try:
            store.last_good_run_starts()
            store.all_jobs()
        except Exception as e:
            errors.append(e)

    worker = threading.Thread(target=use)
    worker.start()
    worker.join()
    store.close()
    assert errors == []
