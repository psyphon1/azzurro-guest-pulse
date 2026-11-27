"""Score the keyword classifier against a hand-labelled gold file.

    python scripts/evaluate_classifier.py [path/to/gold.json]

Each gold case: {id, liked, disliked, expected: [[topic, polarity], ...]}. A prediction is correct
only if both topic and polarity match, at review level (one tag per topic+polarity per review).
Reports precision / recall / F1 per topic and overall, then every miss and false positive.
"""
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from insights.classify import classify_review  # noqa: E402
from insights.topics import TOPICS  # noqa: E402

DEFAULT_GOLD = Path(__file__).parent.parent / "tests" / "fixtures" / "gold_labels.json"


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


@dataclass
class Miss:
    case_id: str
    kind: str  # 'false_positive' | 'false_negative'
    topic: str
    polarity: str
    evidence: str | None = None


@dataclass
class Report:
    per_topic: dict[str, Counts]
    overall: Counts
    misses: list[Miss] = field(default_factory=list)
    cases: int = 0


def evaluate(cases: list[dict]) -> Report:
    per_topic = {t: Counts() for t in TOPICS}
    overall = Counts()
    misses: list[Miss] = []
    for case in cases:
        tags = classify_review(case.get("liked"), case.get("disliked"))
        predicted = {(t.topic, t.polarity): t.evidence for t in tags}
        expected = {(t, p) for t, p in case["expected"]}
        for key in sorted(set(predicted) - expected):
            per_topic[key[0]].fp += 1
            overall.fp += 1
            misses.append(Miss(case["id"], "false_positive", *key, evidence=predicted[key]))
        for key in sorted(expected - set(predicted)):
            per_topic[key[0]].fn += 1
            overall.fn += 1
            misses.append(Miss(case["id"], "false_negative", *key))
        for key in sorted(expected & set(predicted)):
            per_topic[key[0]].tp += 1
            overall.tp += 1
    return Report(per_topic, overall, misses, len(cases))


def format_report(report: Report) -> str:
    lines = [f"Gold cases: {report.cases}", "",
             f"{'topic':<16}{'TP':>4}{'FP':>4}{'FN':>4}{'precision':>11}{'recall':>8}{'F1':>7}"]
    rows = [(t, c) for t, c in report.per_topic.items()] + [("OVERALL", report.overall)]
    for name, c in rows:
        lines.append(f"{name:<16}{c.tp:>4}{c.fp:>4}{c.fn:>4}{c.precision:>11.2f}{c.recall:>8.2f}{c.f1:>7.2f}")
    lines += ["", f"Misses and false positives ({len(report.misses)}):"]
    for m in report.misses:
        extra = f"  <- {m.evidence!r}" if m.evidence else ""
        lines.append(f"  {m.kind:<15} {m.case_id}: {m.topic}/{m.polarity}{extra}")
    return "\n".join(lines)


def split_cases(cases: list[dict], split: str | None) -> list[dict]:
    """The first half is the DEV half (keywords may be tuned against it); the second half is the held-out TEST half
    (only ever looked at to report results). Splitting by position keeps it reproducible and independent of the content."""
    half = len(cases) // 2
    if split == "dev":
        return cases[:half]
    if split == "test":
        return cases[half:]
    return cases


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    split = None
    if "--split" in argv:
        split = argv[argv.index("--split") + 1]
        args = [a for a in args if a != split]
    path = Path(args[0]) if args else DEFAULT_GOLD
    cases = split_cases(json.loads(path.read_text()), split)
    print(format_report(evaluate(cases)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
