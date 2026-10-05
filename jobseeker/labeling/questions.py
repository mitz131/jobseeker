"""Question sets from labels.toml, the /v1/systemone request built from them,
and the answers parsed back into one shape for storage."""

import hashlib
import json
from dataclasses import dataclass

TYPES = ("choice", "noul")


@dataclass(frozen=True)
class Question:
    key: str
    type: str  # "choice" or "noul"
    instructions: str
    options: dict[str, str]  # choice only: option key -> description, in the order given

    def answers(self) -> list[str]:
        """Every answer this question can have."""
        return list(self.options) if self.type == "choice" else ["yes", "no"]


@dataclass(frozen=True)
class QuestionSet:
    name: str
    questions: dict[str, Question]

    def definition(self) -> dict:
        """Canonical form: stored with each run, and hashed to notice edits."""
        return {key: {"type": q.type, "instructions": q.instructions, "options": q.options}
                for key, q in self.questions.items()}

    @property
    def sha(self) -> str:
        # sort_keys=False on purpose: the order of questions and options is part of the set
        return hashlib.sha256(json.dumps(self.definition(), ensure_ascii=False).encode()).hexdigest()[:16]

    def systemone_questions(self) -> dict:
        """The `questions` part of a /v1/systemone request."""
        out = {}
        for key, q in self.questions.items():
            spec = {"type": q.type, "instructions": q.instructions}
            if q.type == "choice":
                spec["criteria"] = dict(q.options)
            out[key] = spec
        return out


def load_question_set(labels_config: dict, name: str) -> QuestionSet:
    sets = labels_config.get("question_sets", {})
    if name not in sets:
        raise ValueError(f"Unknown question set {name!r}; defined: {', '.join(sets) or 'none'}")
    questions = {}
    for key, spec in sets[name].items():
        qtype = spec.get("type")
        if qtype not in TYPES:
            raise ValueError(f"{name}.{key}: type must be one of {TYPES}, not {qtype!r}")
        if not spec.get("instructions"):
            raise ValueError(f"{name}.{key}: instructions missing")
        options = dict(spec.get("options", {}))
        if qtype == "choice" and len(options) < 2:
            raise ValueError(f"{name}.{key}: a choice question needs at least two options")
        if qtype == "noul" and options:
            raise ValueError(f"{name}.{key}: a noul (yes/no) question has no options")
        questions[key] = Question(key, qtype, spec["instructions"], options)
    if not questions:
        raise ValueError(f"Question set {name!r} has no questions")
    return QuestionSet(name, questions)


def load_thresholds(labels_config: dict, backend: str, qs: QuestionSet) -> dict[str, float]:
    """Yes thresholds for one backend answering one question set, from
    [backends.<backend>.thresholds.<set>] in labels.toml: {question: p}, where a yes/no
    answer counts as yes only if p(yes) >= p. Empty when none are set (plain argmax)."""
    raw = labels_config.get("backends", {}).get(backend, {}).get("thresholds", {}).get(qs.name, {})
    for key, t in raw.items():
        q = qs.questions.get(key)
        if q is None or q.type != "noul":
            raise ValueError(f"{backend} thresholds for {qs.name}: {key!r} is not a yes/no question of the set")
        if not isinstance(t, (int, float)) or not 0 < t < 1:
            raise ValueError(f"{backend} thresholds for {qs.name}.{key}: {t!r} must be between 0 and 1")
    return {k: float(t) for k, t in raw.items()}


@dataclass(frozen=True)
class Answer:
    answer: str  # option key, or "yes"/"no"
    probability: float | None  # of `answer`; None for answers without probabilities (Claude, human)
    probabilities: dict[str, float] | None  # all answers


def parse_answer(question: Question, raw: dict) -> Answer:
    """One answer from a /v1/systemone response."""
    if question.type == "choice":
        choice = raw.get("choice")
        probs = {k: float(v) for k, v in (raw.get("probabilities") or {}).items()}
        if choice not in question.options:
            raise ValueError(f"{question.key}: answer {choice!r} is not one of the options")
        return Answer(choice, probs.get(choice), probs or None)
    p_yes = float(raw["noul"])
    answer = "yes" if p_yes >= 0.5 else "no"
    return Answer(answer, p_yes if answer == "yes" else 1 - p_yes, {"yes": p_yes, "no": 1 - p_yes})


def plain_answer(question: Question, value) -> Answer:
    """An answer given without probabilities (imported Claude or human labels)."""
    if question.type == "noul" and isinstance(value, bool):
        value = "yes" if value else "no"
    if value not in question.answers():
        raise ValueError(f"{question.key}: {value!r} is not one of {question.answers()}")
    return Answer(value, None, None)
