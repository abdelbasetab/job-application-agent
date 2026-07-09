"""Offline tests for the golden-set evaluation harness (`job-agent eval`).

These double as a regression gate on Matcher quality: if a rubric change
drops agreement with the human labels below the bounds here, CI fails.
"""

from __future__ import annotations

import json

from job_agent.demo_profile import demo_profile
from job_agent.evaluation import evaluate, load_golden_set


def test_golden_set_loads_and_is_well_formed() -> None:
    cases = load_golden_set()

    assert len(cases) >= 20, "golden set must stay substantial"
    ids = [case.job.id for case in cases]
    assert len(set(ids)) == len(ids), "duplicate job ids in golden set"
    labels = {case.expected for case in cases}
    assert labels == {"strong", "good", "maybe", "skip"}, "all buckets must be covered"


def test_offline_eval_meets_quality_bar() -> None:
    report = evaluate(demo_profile(), threshold=0.6, use_llm=False)

    assert report.accuracy >= 0.7, f"accuracy regressed: {report.accuracy:.2f}"
    assert report.within_one >= 0.9, f"within_one regressed: {report.within_one:.2f}"
    assert report.kappa >= 0.5, f"kappa regressed: {report.kappa:.2f}"
    assert report.spearman >= 0.5, f"spearman regressed: {report.spearman:.2f}"
    assert report.apply_precision >= 0.7
    assert report.apply_recall >= 0.8
    assert report.writer_pass_rate == 1.0, "template letters must pass their own checks"

    # The report must be JSON-serializable for --json-out and CI artifacts.
    payload = json.loads(json.dumps(report.to_dict(), ensure_ascii=False))
    assert payload["n_cases"] == len(report.results)


def test_hard_gate_and_scam_cases() -> None:
    report = evaluate(demo_profile(), use_llm=False)
    by_id = {r.match.job_id: r for r in report.results}

    # Zero skill overlap -> hard gate.
    assert by_id["gold-04"].match.score == 0.0
    assert by_id["gold-19"].match.score == 0.0
    # Scam/ghost patterns -> skip, never a recommendation.
    assert by_id["gold-06"].match.recommendation == "skip"
    assert by_id["gold-07"].match.recommendation == "skip"
    assert by_id["gold-21"].match.recommendation == "skip"
    # Level mismatch is capped below the good band.
    assert by_id["gold-05"].match.score <= 0.55


def test_llm_matcher_agreement_with_mocked_llm(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """With a mocked LLM that echoes the deterministic verdict, agreement is 1.0."""
    import json as _json

    from job_agent.agents.matcher import run_matcher
    from job_agent.schemas import JobPosting

    def fake_llm(messages, **_kwargs):  # type: ignore[no-untyped-def]
        payload = _json.loads(messages[1]["content"].split("\n", 1)[1])
        job = JobPosting.model_validate(payload["job"])
        [deterministic] = run_matcher([job], demo_profile(), use_llm=False)
        return deterministic.model_dump_json()

    monkeypatch.setattr("job_agent.agents.matcher.call_llm", fake_llm)

    cases = load_golden_set()[:6]
    report = evaluate(demo_profile(), threshold=0.6, use_llm=True, cases=cases)

    assert report.llm_comparison is not None
    assert report.llm_comparison["recommendation_agreement"] == 1.0
    assert report.llm_comparison["mean_score_delta"] == 0.0
