"""Pydantic schemas — the typed contracts that flow between agents."""

from job_agent.schemas.job import JobPosting
from job_agent.schemas.profile import UserProfile
from job_agent.schemas.match import MatchResult
from job_agent.schemas.application import GeneratedApplication, ApplicationStatus

__all__ = [
    "JobPosting",
    "UserProfile",
    "MatchResult",
    "GeneratedApplication",
    "ApplicationStatus",
]
