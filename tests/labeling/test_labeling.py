import json

import pytest

from jobseeker.db import JobStore
from jobseeker.labeling.compare import compare_runs
from jobseeker.labeling.questions import load_question_set, load_thresholds, parse_answer
from jobseeker.labeling.runner import import_labels, label_jobs, select_jobs
from jobseeker.labeling.store import LabelStore

CONFIG = {"question_sets": {
    "t1": {
        "seniority": {"type": "choice", "instructions": "Level?",
                      "options": {"junior": "new", "senior": "experienced"}},
        "engineering": {"type": "noul", "instructions": "Engineering job?"},
    },
}}


class FakeKev:
    """Answers like KEV: senior and engineering for titles containing 'Engineer'."""
    url = "http://kev.test"
    model = "kev-latest"

    def __init__(self, fail_titles=()):
        self.fail_titles, self.requests = set(fail_titles), []

    def model_info(self):
        return {"models": [{"name": "kev-latest", "run": "jaredpalmer/kev-4b", "temperature": 2.4}]}

    def ask(self, state, questions):
        self.requests.append((state, questions))
        if any(t in state for t in self.fail_titles):
            raise RuntimeError("HTTP 500")
        eng = "Engineer" in state
        return {"seniority": {"type": "choice", "choice": "senior" if eng else "junior", "confidence": 0.8,
                              "probabilities": {"junior": 0.1, "senior": 0.9} if eng else {"junior": 0.6, "senior": 0.4}},
                "engineering": {"type": "noul", "noul": 0.95 if eng else 0.2}}


@pytest.fixture
def db(tmp_path):
    store = JobStore(str(tmp_path / "jobs.db"))
    with store.conn:
        for i, title in enumerate(["Software Engineer", "Shop assistant", "Data Engineer", "Driver"]):
            store.conn.execute(
                """INSERT INTO jobs (company, job_id, title, location, description, first_seen, last_seen)
                   VALUES ('acme', ?, ?, 'Lausanne', ?, ?, ?)""",
                (f"/job/{i}", title, "x" * 2000, f"2026-10-0{i + 1}", f"2026-10-0{i + 1}"))
    yield store, LabelStore(store.conn)
    store.close()


def test_question_set_keeps_option_order_and_builds_request():
    qs = load_question_set(CONFIG, "t1")
    req = qs.systemone_questions()
    assert list(req) == ["seniority", "engineering"]
    assert list(req["seniority"]["criteria"]) == ["junior", "senior"]
    assert req["engineering"] == {"type": "noul", "instructions": "Engineering job?"}


@pytest.mark.parametrize("bad, message", [
    ({"q": {"type": "score", "instructions": "x"}}, "type must be"),
    ({"q": {"type": "choice", "instructions": "x", "options": {"a": "only one"}}}, "at least two"),
    ({"q": {"type": "noul", "instructions": ""}}, "instructions"),
])
def test_invalid_questions_are_rejected(bad, message):
    with pytest.raises(ValueError, match=message):
        load_question_set({"question_sets": {"bad": bad}}, "bad")


def test_answers_are_parsed_into_one_shape():
    qs = load_question_set(CONFIG, "t1")
    a = parse_answer(qs.questions["seniority"], {"choice": "senior", "probabilities": {"junior": 0.3, "senior": 0.7}})
    assert (a.answer, a.probability) == ("senior", 0.7)
    n = parse_answer(qs.questions["engineering"], {"noul": 0.2})
    assert (n.answer, round(n.probability, 2), n.probabilities["yes"]) == ("no", 0.8, 0.2)
    with pytest.raises(ValueError):
        parse_answer(qs.questions["seniority"], {"choice": "director", "probabilities": {}})


def test_run_stores_answers_with_model_snapshot(db):
    store, labels = db
    qs = load_question_set(CONFIG, "t1")
    kev = FakeKev()
    result = label_jobs(labels, kev, qs, "full", select_jobs(store.conn), "kev4b", note="first try")
    assert (result.labeled, result.failed, result.error) == (4, 0, None)
    run = labels.run(result.run_id)
    assert (run["model"], run["question_set"], run["input_recipe"], run["status"]) == \
        ("jaredpalmer/kev-4b", "t1", "full", "done")
    assert json.loads(run["model_info"])["models"][0]["temperature"] == 2.4
    stored = labels.labels(result.run_id)
    assert stored[("acme", "/job/0")]["seniority"]["answer"] == "senior"
    assert stored[("acme", "/job/1")]["engineering"]["answer"] == "no"
    state = next(st for st, _ in kev.requests if "Software Engineer" in st)  # full text, nothing cut
    assert state == "Job title: Software Engineer\nLocation: Lausanne\n\n" + "x" * 2000


def test_unknown_input_recipe_is_rejected(db):
    store, labels = db
    with pytest.raises(ValueError, match="input recipe"):
        label_jobs(labels, FakeKev(), load_question_set(CONFIG, "t1"), "head1200", select_jobs(store.conn), "kev4b")


def test_failures_are_counted_and_dead_backend_stops_early(db):
    store, labels = db
    qs = load_question_set(CONFIG, "t1")
    partial = label_jobs(labels, FakeKev(fail_titles={"Driver"}), qs, "full", select_jobs(store.conn), "kev4b")
    assert (partial.labeled, partial.failed) == (3, 1)
    assert labels.run(partial.run_id)["status"] == "partial"

    class Down(FakeKev):
        def ask(self, state, questions):
            raise RuntimeError("connection refused")
    jobs = select_jobs(store.conn) * 3  # 12 jobs; should stop after 5 failures
    dead = label_jobs(labels, Down(), qs, "full", jobs, "kev4b")
    assert (dead.labeled, dead.failed) == (0, 5) and "gave up" in dead.error
    assert labels.run(dead.run_id)["status"] == "failed"


def test_edited_question_set_needs_a_new_name(db):
    store, labels = db
    label_jobs(labels, FakeKev(), load_question_set(CONFIG, "t1"), "full", select_jobs(store.conn, limit=1), "kev4b")
    edited = {"question_sets": {"t1": dict(CONFIG["question_sets"]["t1"],
                                           engineering={"type": "noul", "instructions": "Is it engineering?"})}}
    with pytest.raises(ValueError, match="new name"):
        label_jobs(labels, FakeKev(), load_question_set(edited, "t1"), "full", select_jobs(store.conn), "kev4b")


def test_import_and_compare(db):
    store, labels = db
    qs = load_question_set(CONFIG, "t1")
    kev = label_jobs(labels, FakeKev(), qs, "full", select_jobs(store.conn), "kev4b")
    claude = import_labels(labels, store.conn, qs, [
        {"company": "acme", "job_id": "/job/0", "answers": {"seniority": "senior", "engineering": "yes"}},
        {"company": "acme", "job_id": "/job/1", "answers": {"seniority": "junior", "engineering": False}},
        {"company": "acme", "job_id": "/job/2", "answers": {"seniority": "junior", "engineering": "yes"}},
        {"company": "acme", "job_id": "/job/404", "answers": {"seniority": "junior"}},       # no such job
        {"company": "acme", "job_id": "/job/3", "answers": {"seniority": "lead"}},            # not an option
    ], backend="claude", model="claude-opus-5-5", recipe="full")
    assert (claude.labeled, claude.failed) == (3, 2)

    by_q = {r.question: r for r in compare_runs(labels, kev.run_id, claude.run_id)}
    assert (by_q["seniority"].common, by_q["seniority"].agree) == (3, 2)
    assert by_q["seniority"].differences == [(("senior", "junior"), 1)]
    assert by_q["engineering"].agreement == 1.0
    # KEV was 0.9 sure on the engineering titles, 0.6 on the shop assistant
    assert by_q["seniority"].by_confidence[0.7] == (2, 1)
    assert compare_runs(labels, claude.run_id, kev.run_id)[0].by_confidence == {}  # imported: no probabilities


def test_thresholds_apply_when_reading_and_keep_stored_answers(db):
    store, labels = db
    qs = load_question_set(CONFIG, "t1")
    kev = label_jobs(labels, FakeKev(), qs, "full", select_jobs(store.conn), "kev4b")  # engineering p(yes) 0.95 / 0.2
    plain = labels.labels(kev.run_id)
    assert plain[("acme", "/job/0")]["engineering"]["answer"] == "yes"

    strict = labels.labels(kev.run_id, {"engineering": 0.99})
    job0 = strict[("acme", "/job/0")]["engineering"]
    assert (job0["answer"], round(job0["probability"], 2), job0["stored_answer"]) == ("no", 0.05, "yes")
    assert strict[("acme", "/job/0")]["seniority"]["answer"] == "senior"  # choice questions untouched

    lenient = labels.labels(kev.run_id, {"engineering": 0.1})
    assert all(a["engineering"]["answer"] == "yes" for a in lenient.values())

    claude = import_labels(labels, store.conn, qs, [
        {"company": "acme", "job_id": "/job/0", "answers": {"seniority": "senior", "engineering": "yes"}},
    ], backend="claude", model="claude-opus-5-5", recipe="full")
    assert labels.labels(claude.run_id, {"engineering": 0.99})[("acme", "/job/0")]["engineering"]["answer"] == "yes"
    by_q = {r.question: r for r in compare_runs(labels, kev.run_id, claude.run_id,
                                                thresholds={kev.run_id: {"engineering": 0.99}})}
    assert by_q["engineering"].differences == [(("no", "yes"), 1)]


@pytest.mark.parametrize("thresholds, message", [
    ({"seniority": 0.6}, "not a yes/no question"),
    ({"nope": 0.6}, "not a yes/no question"),
    ({"engineering": 1.5}, "between 0 and 1"),
])
def test_invalid_thresholds_are_rejected(thresholds, message):
    config = dict(CONFIG, backends={"kev4b": {"thresholds": {"t1": thresholds}}})
    with pytest.raises(ValueError, match=message):
        load_thresholds(config, "kev4b", load_question_set(config, "t1"))


def test_thresholds_are_per_backend_and_question_set():
    config = dict(CONFIG, backends={"kev4b": {"thresholds": {"t1": {"engineering": 0.7}}}})
    qs = load_question_set(config, "t1")
    assert load_thresholds(config, "kev4b", qs) == {"engineering": 0.7}
    assert load_thresholds(config, "claude", qs) == {}


def test_runs_of_different_question_sets_are_not_compared(db):
    store, labels = db
    other = {"question_sets": {"t2": {"engineering": {"type": "noul", "instructions": "Engineering?"}}}}
    a = label_jobs(labels, FakeKev(), load_question_set(CONFIG, "t1"), "full", select_jobs(store.conn), "kev4b")
    b = label_jobs(labels, FakeKev(), load_question_set(other, "t2"), "full", select_jobs(store.conn), "kev4b")
    with pytest.raises(ValueError, match="same question set"):
        compare_runs(labels, a.run_id, b.run_id)
