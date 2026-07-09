"""Evaluation harness — measurable Matcher/Writer quality (``job-agent eval``)."""

from job_agent.evaluation.harness import (
    CaseResult,
    EvalReport,
    GoldenCase,
    evaluate,
    load_golden_set,
)

__all__ = [
    "CaseResult",
    "EvalReport",
    "GoldenCase",
    "evaluate",
    "load_golden_set",
]
