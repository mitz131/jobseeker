"""Compare two labelling runs of the same question set, question by question."""

import json
from collections import Counter
from dataclasses import dataclass, field

from .store import LabelStore

THRESHOLDS = (0.5, 0.7, 0.9)


@dataclass
class QuestionComparison:
    question: str
    common: int  # jobs answered in both runs
    agree: int
    differences: list[tuple[tuple[str, str], int]]  # most frequent (answer A, answer B) pairs
    # threshold -> (jobs where run A's probability >= threshold, of which agree); empty
    # when run A has no probabilities
    by_confidence: dict[float, tuple[int, int]] = field(default_factory=dict)

    @property
    def agreement(self) -> float | None:
        return self.agree / self.common if self.common else None


def compare_runs(labels: LabelStore, run_a: int, run_b: int, top: int = 3) -> list[QuestionComparison]:
    a, b = labels.run(run_a), labels.run(run_b)
    for run_id, run in ((run_a, a), (run_b, b)):
        if run is None:
            raise ValueError(f"No label run {run_id}")
    if a["question_set"] != b["question_set"]:
        raise ValueError(f"Run {run_a} answered {a['question_set']!r} and run {run_b} {b['question_set']!r}: "
                         "only runs of the same question set can be compared")
    definition = json.loads(labels.conn.execute(
        "SELECT definition FROM question_sets WHERE name = ?", (a["question_set"],)).fetchone()[0])
    la, lb = labels.labels(run_a), labels.labels(run_b)
    jobs = sorted(set(la) & set(lb))

    out = []
    for question in definition:
        pairs = [(la[j][question], lb[j][question]) for j in jobs if question in la[j] and question in lb[j]]
        diffs = Counter((x["answer"], y["answer"]) for x, y in pairs if x["answer"] != y["answer"])
        result = QuestionComparison(
            question=question, common=len(pairs),
            agree=sum(x["answer"] == y["answer"] for x, y in pairs),
            differences=diffs.most_common(top))
        if pairs and all(x["probability"] is not None for x, _ in pairs):
            for t in THRESHOLDS:
                sure = [(x, y) for x, y in pairs if x["probability"] >= t]
                result.by_confidence[t] = (len(sure), sum(x["answer"] == y["answer"] for x, y in sure))
        out.append(result)
    return out
