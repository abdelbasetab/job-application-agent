

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from job_agent.agents.matcher import run_matcher
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
from job_agent.utils.config import settings
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


def run_scout(
    profile: UserProfile,
    query: str | None = None,
    limit: int = 5,
) -> list[JobPosting]:
    """Lazy live Scout wrapper so demo/test paths stay fully offline."""
    from job_agent.agents.scout import run_scout as live_run_scout

    return live_run_scout(profile, query, limit)


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
    scout_runner: Callable[[UserProfile, str | None, int], list[JobPosting]] | None = None,
    use_llm_agents: bool | None = None,
    use_chroma: bool | None = None,
    chroma_path: str | Path | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> PipelineResult:
    """Run the full Scout → Matcher → Writer → Tracker chain."""
    result = PipelineResult()

    def _emit(stage: str, pct: int) -> None:
        if progress is not None:
            progress(stage, pct)
    scout = scout_runner or run_scout
    llm_enabled = settings.enable_llm_agents if use_llm_agents is None else use_llm_agents
    chroma_enabled = settings.enable_chroma if use_chroma is None else use_chroma
    profile_fingerprint = store.save_profile(profile, source="pipeline")
    context_by_job: dict[str, list[str]] = {}

    _emit("Scout: Jobs suchen", 10)
    log.info("=== [1/4] Scout ===")
    result.jobs = scout(profile, query, job_limit)
    for job in result.jobs:
        store.save_job(job)

    if chroma_enabled:
        from job_agent.memory.profile_index import ProfileVectorStore

        index = ProfileVectorStore(path=chroma_path)
        index.upsert_profile(profile)
        for job in result.jobs:
            context_query = " ".join(
                [job.title, job.description[:1000], *job.requirements[:10]]
            )
            context_by_job[job.id] = index.query(context_query, top_k=3)
        log.info("[pipeline] loaded per-job profile context for %d jobs", len(result.jobs))

    _emit("Matcher: Bewertung", 45)
    log.info("=== [2/4] Matcher ===")
    for job in result.jobs:
        matched = run_matcher(
            [job],
            profile,
            threshold=match_threshold,
            use_llm=llm_enabled,
            profile_context=context_by_job.get(job.id, []),
        )[0]
        result.matches.append(matched)
        store.save_match(matched, profile_fingerprint)
    by_id = {j.id: j for j in result.jobs}

    _emit("Writer: Anschreiben", 70)
    log.info("=== [3/4] Writer (threshold=%.2f) ===", match_threshold)
    qualifying = [m for m in result.matches if m.score >= match_threshold]
    fresh, skipped = [], 0
    for m in qualifying:
        if store.job_exists(m.job_id):
            skipped += 1
            continue
        fresh.append(m)
    if skipped:
        log.info("[pipeline] skipping %d already-applied jobs", skipped)
    for match in fresh:
        job = by_id[match.job_id]
        app = run_writer(
            job=job,
            match=match,
            profile=profile,
            use_llm=llm_enabled,
            profile_context=context_by_job.get(job.id, []),
        )
        result.applications.append(app)

    _emit("Tracker: Speichern", 90)
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
    _emit("Fertig", 100)
    return result
