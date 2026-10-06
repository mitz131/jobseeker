import threading

import pytest
from fastapi.testclient import TestClient

from jobseeker.api.app import create_app
from jobseeker.db import JobStore
from jobseeker.labeling.questions import load_question_set, parse_answer
from jobseeker.labeling.store import LabelStore
from tests.api.test_app import FRESH, config  # noqa: F401  (config is a fixture)

LABELS = '''
[current]
backend = "kev"
questions = "t1"

[backends.kev]
url = "http://kev.test"

[backends.kev.thresholds.t1]
german_required = 0.7

[question_sets.t1.seniority]
type = "choice"
instructions = "Level?"
[question_sets.t1.seniority.options]
junior = "new"
experienced = "some years"

[question_sets.t1.german_required]
type = "noul"
instructions = "German required?"
'''


def raw(seniority, p_german):
    probs = {"junior": 0.8, "experienced": 0.2} if seniority == "junior" else {"junior": 0.2, "experienced": 0.8}
    return {"seniority": {"choice": seniority, "probabilities": probs}, "german_required": {"noul": p_german}}


class FakeKev:
    url = "http://kev.test"
    model = "kev-latest"

    def __init__(self, up=True, gate=None):
        self.up, self.gate, self.asked = up, gate, []

    def model_info(self):
        return {"models": [{"run": "jaredpalmer/kev-4b"}]} if self.up else None

    def ask(self, state, questions):
        if self.gate:
            self.gate.wait(timeout=5)
        self.asked.append(state.splitlines()[0])
        return raw("experienced", 0.95)


@pytest.fixture
def labelled(config, tmp_path):  # noqa: F811
    """acme/1 experienced, German p=0.6 (no at threshold 0.7); acme/2 junior, German 0.9;
    beta/5 experienced, German 0.1; the other two jobs have no labels."""
    (tmp_path / "labels.toml").write_text(LABELS)
    qs = load_question_set(config.labels, "t1")
    store = JobStore(str(config.db_path))
    labels = LabelStore(store.conn)
    labels.register_question_set(qs)
    run = labels.start_run("kev", "http://kev.test", "jaredpalmer/kev-4b", {}, "t1", "full", None)
    for co, jid, answer in (("acme", "1", raw("experienced", 0.6)), ("acme", "2", raw("junior", 0.9)),
                            ("beta", "5", raw("experienced", 0.1))):
        labels.add_answers(run, co, jid, {k: parse_answer(q, answer[k]) for k, q in qs.questions.items()}, answer)
    labels.finish_run(run, 3, 0)
    store.close()
    return config


def client(config, label_client=None):
    app = create_app(config, batch=lambda: None, max_age=FRESH, label_client=label_client)
    return TestClient(app), app.state.refresher


def by_id(resp):
    return {i["job_id"]: i for i in resp.json()["items"]}


def test_jobs_carry_current_labels_with_thresholds(labelled):
    c, _ = client(labelled)
    jobs = by_id(c.get("/api/jobs"))
    assert jobs["1"]["labels"]["seniority"] == {"answer": "experienced", "probability": 0.8}
    german = jobs["1"]["labels"]["german_required"]   # p(yes) 0.6 is below the 0.7 threshold
    assert german["answer"] == "no" and round(german["probability"], 2) == 0.4
    assert jobs["2"]["labels"]["german_required"]["answer"] == "yes"
    assert jobs["/job/Zurich/Dev_JR1"]["labels"] is None   # not labelled yet
    one = c.get("/api/jobs/acme/1").json()
    assert one["labels"]["seniority"]["answer"] == "experienced" and one["description"]


def test_label_filters_keep_unlabelled_jobs(labelled):
    c, _ = client(labelled)
    assert set(by_id(c.get("/api/jobs", params={"label": "seniority:junior"}))) == {"2", "/job/Zurich/Dev_JR1"}
    both = c.get("/api/jobs", params={"label": ["seniority:junior", "seniority:experienced"]})
    assert set(by_id(both)) == {"1", "2", "5", "/job/Zurich/Dev_JR1"}   # alternatives of one question
    combined = c.get("/api/jobs", params={"label": ["seniority:experienced", "german_required:no"]})
    assert set(by_id(combined)) == {"1", "5", "/job/Zurich/Dev_JR1"}    # all questions must match


@pytest.mark.parametrize("value, message", [
    ("nope:yes", "Unknown label question"),
    ("seniority:director", "is not one of"),
    ("seniority", "is not one of"),
])
def test_bad_label_filters(labelled, value, message):
    c, _ = client(labelled)
    resp = c.get("/api/jobs", params={"label": value})
    assert resp.status_code == 400 and message in resp.json()["detail"]


def test_label_info_and_unlabelled_count(labelled):
    c, _ = client(labelled)
    info = c.get("/api/labels").json()
    assert (info["backend"], info["question_set"], info["thresholds"]) == ("kev", "t1", {"german_required": 0.7})
    assert [q["key"] for q in info["questions"]] == ["seniority", "german_required"]
    assert [o["key"] for o in info["questions"][0]["options"]] == ["junior", "experienced"]
    assert [o["key"] for o in info["questions"][1]["options"]] == ["yes", "no"]
    assert c.get("/api/status").json()["unlabelled"] == 2   # the Zurich developer and the closed job


def test_labelling_in_the_background(labelled):
    gate = threading.Event()
    kev = FakeKev(gate=gate)
    c, refresher = client(labelled, label_client=kev)
    assert c.post("/api/label").json()["started"] is True
    status = c.get("/api/status").json()
    assert status["refresh_running"] is True and status["refresh_phase"] == "labelling"
    assert status["refresh_total"] == 2
    assert c.post("/api/label").json() == {"started": False, "reason": "a background job is already running"}
    gate.set()
    assert refresher.wait(timeout=5)
    status = c.get("/api/status").json()
    assert status["refresh_running"] is False and status["refresh_phase"] is None
    assert status["unlabelled"] == 0 and status["refresh_note"] is None
    assert sorted(kev.asked) == ["Job title: Developer", "Job title: Withdrawn job"]   # only unlabelled jobs
    assert by_id(c.get("/api/jobs"))["/job/Zurich/Dev_JR1"]["labels"]["seniority"]["answer"] == "experienced"
    assert by_id(c.get("/api/jobs"))["1"]["labels"]["german_required"]["answer"] == "no"   # older run kept


def test_unreachable_backend_skips_labelling(labelled):
    c, refresher = client(labelled, label_client=FakeKev(up=False))
    c.post("/api/label")
    assert refresher.wait(timeout=5)
    status = c.get("/api/status").json()
    assert status["refresh_error"] is None
    assert status["refresh_note"] == "Labelling skipped: kev is not reachable at http://kev.test"
    assert status["unlabelled"] == 2


def test_without_labels_configured(config):  # noqa: F811
    c, _ = client(config)
    assert all(i["labels"] is None for i in c.get("/api/jobs").json()["items"])
    assert c.get("/api/labels").status_code == 404
    assert c.post("/api/label").status_code == 404
    assert c.get("/api/jobs", params={"label": "seniority:junior"}).status_code == 400
    assert c.get("/api/status").json()["unlabelled"] is None
