"""Evaluation harness for the Matcher (and Writer) against a labeled golden set.

The golden set (``golden_set.yaml``) holds ~24 job postings with a human
ground-truth label (``strong`` / ``good`` / ``maybe`` / ``skip``) relative to
the baked-in demo profile. The harness scores every posting and reports:

- **accuracy** — exact recommendation matches,
- **within_one** — predictions at most one bucket away (ordinal scale),
- **kappa** — Cohen's kappa (chance-corrected agreement),
- **spearman** — rank correlation between score and the human ordinal,
- **apply precision/recall** — the threshold decision ("draft a letter?")
  against the human "would apply" labels (good/strong),
- **writer_pass_rate** — fraction of drafted letters passing all quality checks.

With ``use_llm=True`` the same cases go through the LLM matcher and the
report additionally compares LLM vs deterministic verdicts (agreement,
kappa, mean score delta) — including the effect of RAG profile context.

Everything runs offline by default: no network, no LLM, deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from job_agent.agents.matcher import run_matcher
from job_agent.agents.writer import run_writer
from job_agent.schemas import JobPosting, MatchResult, Recommendation, UserProfile
from job_agent.utils.llm import telemetry
from job_agent.utils.logging import get_logger

log = get_logger(__name__)

_GOLDEN_PATH = Path(__file__).resolve().parent / "golden_set.yaml"
_ORDINAL: dict[str, int] = {"skip": 0, "maybe": 1, "good": 2, "strong": 3}
_APPLY_LABELS = {"good", "strong"}


@dataclass
class GoldenCase:
    """One labeled evaluation example."""

    job: JobPosting
    expected: Recommendation
    note: str = ""


@dataclass
class CaseResult:
    """A golden case together with the Matcher's verdict."""

    case: GoldenCase
    match: MatchResult

    @property
    def hit(self) -> bool:
        return self.match.recommendation == self.case.expected

    @property
    def distance(self) -> int:
        return abs(_ORDINAL[self.match.recommendation] - _ORDINAL[self.case.expected])


@dataclass
class EvalReport:
    """Aggregated metrics over the golden set."""

    results: list[CaseResult]
    threshold: float
    accuracy: float
    within_one: float
    kappa: float
    spearman: float
    apply_precision: float
    apply_recall: float
    writer_pass_rate: float
    llm_comparison: dict[str, float] | None = None
    telemetry_summary: dict[str, float] | None = None

    @property
    def misses(self) -> list[CaseResult]:
        return [r for r in self.results if not r.hit]

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable view (written by ``job-agent eval --json-out``)."""
        return {
            "n_cases": len(self.results),
            "threshold": self.threshold,
            "accuracy": round(self.accuracy, 3),
            "within_one": round(self.within_one, 3),
            "kappa": round(self.kappa, 3),
            "spearman": round(self.spearman, 3),
            "apply_precision": round(self.apply_precision, 3),
            "apply_recall": round(self.apply_recall, 3),
            "writer_pass_rate": round(self.writer_pass_rate, 3),
            "llm_comparison": self.llm_comparison,
            "telemetry": self.telemetry_summary,
            "misses": [
                {
                    "job_id": r.match.job_id,
                    "title": r.case.job.title,
                    "expected": r.case.expected,
                    "got": r.match.recommendation,
                    "score": r.match.score,
                    "note": r.case.note,
                }
                for r in self.misses
            ],
        }


def load_golden_set(path: str | Path | None = None) -> list[GoldenCase]:
    """Load and validate the golden set.

    ``posted_days_ago`` (relative age) is translated into a concrete
    ``posted_at`` at load time so age-based risk cases do not go stale as
    real time passes.
    """
    source = Path(path) if path else _GOLDEN_PATH
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"Golden set must be a YAML list: {source}")

    cases: list[GoldenCase] = []
    for entry in raw:
        job_data = dict(entry["job"])
        days_ago = job_data.pop("posted_days_ago", None)
        if days_ago is not None:
            job_data["posted_at"] = (date.today() - timedelta(days=int(days_ago))).isoformat()
        expected = str(entry["expected"])
        if expected not in _ORDINAL:
            raise ValueError(f"Unknown expected label '{expected}' in {source}")
        cases.append(
            GoldenCase(
                job=JobPosting.model_validate(job_data),
                expected=expected,  # type: ignore[arg-type]
                note=str(entry.get("note", "")),
            )
        )
    log.info("[eval] loaded %d golden cases from %s", len(cases), source)
    return cases


def evaluate(
    profile: UserProfile,
    threshold: float = 0.6,
    use_llm: bool = False,
    profile_context: list[str] | None = None,
    cases: list[GoldenCase] | None = None,
    compare_llm_to_deterministic: bool = True,
) -> EvalReport:
    """Score the golden set with the Matcher and aggregate quality metrics."""
    golden = cases if cases is not None else load_golden_set()
    jobs = [case.job for case in golden]

    telemetry.reset()
    matches = run_matcher(
        jobs,
        profile,
        threshold=threshold,
        use_llm=use_llm,
        profile_context=profile_context,
    )
    results = [
        CaseResult(case=case, match=match)
        for case, match in zip(golden, matches, strict=True)
    ]

    llm_comparison: dict[str, float] | None = None
    if use_llm and compare_llm_to_deterministic:
        baseline = run_matcher(jobs, profile, threshold=threshold, use_llm=False)
        llm_comparison = _compare(matches, baseline)

    report = EvalReport(
        results=results,
        threshold=threshold,
        accuracy=_mean([1.0 if r.hit else 0.0 for r in results]),
        within_one=_mean([1.0 if r.distance <= 1 else 0.0 for r in results]),
        kappa=_cohens_kappa(
            [r.case.expected for r in results],
            [r.match.recommendation for r in results],
        ),
        spearman=_spearman(
            [float(_ORDINAL[r.case.expected]) for r in results],
            [r.match.score for r in results],
        ),
        apply_precision=_apply_metric(results, threshold, precision=True),
        apply_recall=_apply_metric(results, threshold, precision=False),
        writer_pass_rate=_writer_pass_rate(results, profile, threshold, use_llm),
        llm_comparison=llm_comparison,
        telemetry_summary=telemetry.summary(),
    )
    log.info(
        "[eval] n=%d accuracy=%.2f within_one=%.2f kappa=%.2f spearman=%.2f",
        len(results),
        report.accuracy,
        report.within_one,
        report.kappa,
        report.spearman,
    )
    return report


def _writer_pass_rate(
    results: list[CaseResult],
    profile: UserProfile,
    threshold: float,
    use_llm: bool,
) -> float:
    """Draft a letter for every qualifying match; report the all-checks pass rate."""
    passes: list[float] = []
    for result in results:
        if result.match.score < threshold:
            continue
        app = run_writer(result.case.job, result.match, profile, use_llm=use_llm)
        passes.append(1.0 if all(app.quality_checks.values()) else 0.0)
    return _mean(passes) if passes else 1.0


def _compare(llm: list[MatchResult], baseline: list[MatchResult]) -> dict[str, float]:
    """LLM matcher vs deterministic matcher on identical inputs."""
    agreement = _mean(
        [1.0 if a.recommendation == b.recommendation else 0.0 for a, b in zip(llm, baseline, strict=True)]
    )
    kappa = _cohens_kappa(
        [b.recommendation for b in baseline],
        [a.recommendation for a in llm],
    )
    mean_delta = _mean([abs(a.score - b.score) for a, b in zip(llm, baseline, strict=True)])
    return {
        "recommendation_agreement": round(agreement, 3),
        "kappa_vs_deterministic": round(kappa, 3),
        "mean_score_delta": round(mean_delta, 3),
    }


def _apply_metric(results: list[CaseResult], threshold: float, precision: bool) -> float:
    """Precision/recall of the 'draft an application' decision."""
    tp = sum(
        1
        for r in results
        if r.match.score >= threshold and r.case.expected in _APPLY_LABELS
    )
    fp = sum(
        1
        for r in results
        if r.match.score >= threshold and r.case.expected not in _APPLY_LABELS
    )
    fn = sum(
        1
        for r in results
        if r.match.score < threshold and r.case.expected in _APPLY_LABELS
    )
    if precision:
        return tp / (tp + fp) if (tp + fp) else 1.0
    return tp / (tp + fn) if (tp + fn) else 1.0


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _cohens_kappa(expected: list[str], predicted: list[str]) -> float:
    """Chance-corrected agreement between two label sequences."""
    n = len(expected)
    if not n:
        return 0.0
    po = sum(1 for e, p in zip(expected, predicted, strict=True) if e == p) / n
    labels = set(expected) | set(predicted)
    pe = sum(
        (expected.count(label) / n) * (predicted.count(label) / n) for label in labels
    )
    if pe >= 1.0:
        return 1.0
    return (po - pe) / (1.0 - pe)


def _spearman(xs: list[float], ys: list[float]) -> float:
    """Spearman rank correlation with average ranks for ties."""
    if len(xs) < 2:
        return 0.0
    rank_x = _average_ranks(xs)
    rank_y = _average_ranks(ys)
    mean_x = _mean(rank_x)
    mean_y = _mean(rank_y)
    cov = sum((a - mean_x) * (b - mean_y) for a, b in zip(rank_x, rank_y, strict=True))
    var_x = sum((a - mean_x) ** 2 for a in rank_x) ** 0.5
    var_y = sum((b - mean_y) ** 2 for b in rank_y) ** 0.5
    if not var_x or not var_y:
        return 0.0
    return float(cov / (var_x * var_y))


def _average_ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks
