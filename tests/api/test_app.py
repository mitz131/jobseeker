import threading
from datetime import timedelta
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from jobseeker.api.app import create_app
from jobseeker.config import Config
from jobseeker.db import JobStore
from tests.test_places import HEADER, ROWS

FRESH = timedelta(days=36500)  # data never counts as stale
STALE = timedelta(0)           # data always counts as stale

CONFIG = '''
[settings]
db_path = "data/jobs.db"
places_register = "register.csv"
places_file = "places.toml"

[[company]]
name = "acme"
type = "workday"
'''
PLACES = '''
[regions]
"Riviera" = ["Vevey", "Montreux"]
'''
JOBS = [
    # company, job_id, title, location, first_seen, last_seen
    ("acme", "1", "Engineer", "Vevey, VD", "2026-10-01T08:00:00+00:00", "2026-10-03T09:01:00+00:00"),
    ("acme", "2", "Analyst", "Riviera", "2026-10-02T08:00:00+00:00", "2026-10-03T09:01:00+00:00"),
    ("acme", "3", "Withdrawn job", "Lausanne", "2026-08-01T08:00:00+00:00", "2026-09-01T08:00:00+00:00"),
    ("beta", "/job/Zurich/Dev_JR1", "Developer", "Zürich", "2026-09-30T08:00:00+00:00", "2026-10-03T09:01:00+00:00"),
    ("beta", "5", "Remote advisor", "Suisse", "2026-10-03T08:00:00+00:00", "2026-10-03T09:01:00+00:00"),
]


@pytest.fixture
def config(tmp_path):
    (tmp_path / "config.toml").write_text(CONFIG)
    (tmp_path / "places.toml").write_text(PLACES)
    with open(tmp_path / "register.csv", "w", encoding="utf-8-sig") as f:
        f.write(HEADER + "\n")
        for name, plz, muni, canton, share, e, n in ROWS:
            f.write(f"{name};{plz};0;0;{muni};0;{canton};{share};{e};{n};fr;2008-07-01\n")
    cfg = Config.load(tmp_path / "config.toml")
    store = JobStore(str(cfg.db_path))
    with store.conn:
        for co, jid, title, loc, first, last in JOBS:
            store.conn.execute(
                """INSERT INTO jobs (company, job_id, title, location, url, description, first_seen, last_seen)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (co, jid, title, loc, f"https://jobs.example/{jid}", f"About {title}", first, last))
        for co in ("acme", "beta"):
            store.conn.execute(
                "INSERT INTO runs (company, started_at, finished_at, listed, new) VALUES (?, ?, ?, 3, 0)",
                (co, "2026-10-03T09:00:00+00:00", "2026-10-03T09:05:00+00:00"))
    store.close()
    return cfg


def client_for(config, max_age=FRESH, batch=lambda: None):
    app = create_app(config, batch=batch, max_age=max_age)
    return TestClient(app), app.state.refresher


def ids(resp):
    return [i["job_id"] for i in resp.json()["items"]]


def test_open_jobs_newest_first(config):
    client, _ = client_for(config)
    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    assert ids(resp) == ["5", "2", "1", "/job/Zurich/Dev_JR1"]
    assert resp.json()["total"] == 4
    assert all(i["open"] for i in resp.json()["items"])


def test_closed_jobs_on_request(config):
    client, _ = client_for(config)
    items = client.get("/api/jobs", params={"include_closed": True}).json()["items"]
    assert {i["job_id"]: i["open"] for i in items}["3"] is False
    assert len(items) == 5


def test_distance_sort_regions_at_zero_unknown_last(config):
    client, _ = client_for(config)
    body = client.get("/api/jobs", params={"home": "1800", "sort": "distance"}).json()
    assert body["home"] == "Vevey (VD)"
    by_id = {i["job_id"]: i for i in body["items"]}
    assert by_id["1"]["distance_km"] == 0.0
    assert by_id["2"]["distance_km"] == 0.0
    assert by_id["2"]["nearest"] == "Vevey, via region Riviera (2 localities)"
    assert by_id["5"]["distance_km"] is None
    assert ids(client.get("/api/jobs", params={"home": "1800", "sort": "distance"}))[-2:] == ["/job/Zurich/Dev_JR1", "5"]


def test_max_km_excludes_far_and_unknown(config):
    client, _ = client_for(config)
    assert sorted(ids(client.get("/api/jobs", params={"home": "Vevey", "max_km": 5}))) == ["1", "2"]


def test_company_and_location_filters(config):
    client, _ = client_for(config)
    assert sorted(ids(client.get("/api/jobs", params={"company": "beta"}))) == ["/job/Zurich/Dev_JR1", "5"]
    assert ids(client.get("/api/jobs", params={"location": "zurich"})) == ["/job/Zurich/Dev_JR1"]  # Zürich
    assert sorted(ids(client.get("/api/jobs", params=[("company", "acme"), ("company", "beta")]))) == \
        sorted(["5", "2", "1", "/job/Zurich/Dev_JR1"])


def test_limit_and_offset_keep_total(config):
    client, _ = client_for(config)
    body = client.get("/api/jobs", params={"limit": 2, "offset": 1}).json()
    assert body["total"] == 4
    assert [i["job_id"] for i in body["items"]] == ["2", "1"]


@pytest.mark.parametrize("params, status", [
    ({"max_km": 10}, 400),
    ({"sort": "distance"}, 400),
    ({"home": "Weinsteinjoch"}, 400),
    ({"sort": "random"}, 422),
])
def test_bad_queries(config, params, status):
    client, _ = client_for(config)
    assert client.get("/api/jobs", params=params).status_code == status


def test_single_job_with_slash_in_id(config):
    client, _ = client_for(config)
    resp = client.get("/api/jobs/beta/" + quote("/job/Zurich/Dev_JR1", safe=""))
    assert resp.status_code == 200
    assert resp.json()["description"] == "About Developer"
    assert client.get("/api/jobs/acme/999").status_code == 404


def test_status(config):
    client, _ = client_for(config, max_age=STALE)
    body = client.get("/api/status").json()
    assert body["last_update"] == "2026-10-03T09:05:00+00:00"
    assert body["stale"] is True
    assert [c["company"] for c in body["companies"]] == ["acme", "beta"]
    assert body["refresh_running"] is False


def test_refresh_only_when_stale_unless_forced(config):
    calls = []
    client, refresher = client_for(config, max_age=FRESH, batch=lambda: calls.append(1))
    assert client.post("/api/refresh").json() == {"started": False, "reason": "data is up to date"}
    assert client.post("/api/refresh", params={"force": True}).json()["started"] is True
    assert refresher.wait(timeout=5)
    assert calls == [1]


def test_one_refresh_at_a_time(config):
    release, calls = threading.Event(), []

    def slow_batch():
        calls.append(1)
        release.wait(timeout=5)

    client, refresher = client_for(config, max_age=STALE, batch=slow_batch)
    assert client.post("/api/refresh").json()["started"] is True
    assert client.get("/api/status").json()["refresh_running"] is True
    assert client.post("/api/refresh").json() == {"started": False, "reason": "a refresh is already running"}
    release.set()
    assert refresher.wait(timeout=5)
    status = client.get("/api/status").json()
    assert calls == [1]
    assert status["refresh_running"] is False and status["refresh_finished_at"]


def test_crashing_batch_is_reported(config):
    def broken():
        raise RuntimeError("network down")

    client, refresher = client_for(config, max_age=STALE, batch=broken)
    client.post("/api/refresh")
    assert refresher.wait(timeout=5)
    assert client.get("/api/status").json()["refresh_error"] == "network down"


def test_swagger_docs(config):
    client, _ = client_for(config)
    assert client.get("/docs").status_code == 200
    assert "/api/jobs" in client.get("/openapi.json").json()["paths"]
