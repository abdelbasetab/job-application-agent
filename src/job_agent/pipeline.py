

from __future__ import annotations

from dataclasses import dataclass, field

from job_agent.agents.matcher import run_matcher
from job_agent.agents.scout import run_scout
from job_agent.agents.tracker import run_tracker
from job_agent.agents.writer import run_writer
from job_agent.memory.store import Store
from job_agent.schemas import (
    ApplicationStatus,
    GeneratedApplication,
    JobPosting,
    MatchResult,
    UserProfile,
)
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


@dataclass
class PipelineResult:
    """Everything the pipeline produced, in one inspectable object."""

    jobs: list[JobPosting] = field(default_factory=list)
    matches: list[MatchResult] = field(default_factory=list)
    applications: list[GeneratedApplication] = field(default_factory=list)
    statuses: list[ApplicationStatus] = field(default_factory=list)


def run_pipeline(
    profile: UserProfile,
    store: Store,
    query: str | None = None,
    match_threshold: float = 0.6,
    job_limit: int = 5,
) -> PipelineResult:
    """Run the full Scout → Matcher → Writer → Tracker chain."""
    result = PipelineResult()

    log.info("=== [1/4] Scout ===")
    result.jobs = run_scout(profile, query=query, limit=job_limit)
    for job in result.jobs:
        store.save_job(job)

    log.info("=== [2/4] Matcher ===")
    result.matches = run_matcher(result.jobs, profile, threshold=match_threshold)
    by_id = {j.id: j for j in result.jobs}

    log.info("=== [3/4] Writer (threshold=%.2f) ===", match_threshold)
    qualifying = [m for m in result.matches if m.score >= match_threshold]
    for match in qualifying:
        job = by_id[match.job_id]
        app = run_writer(job=job, match=match, profile=profile)
        result.applications.append(app)

    log.info("=== [4/4] Tracker ===")
    for app in result.applications:
        status = run_tracker(application=app, store=store, status="draft")
        result.statuses.append(status)

    log.info(
        "Pipeline complete — jobs=%d matches=%d qualifying=%d drafts=%d",
        len(result.jobs),
        len(result.matches),
        len(qualifying),
        len(result.applications),
    )
    return result
