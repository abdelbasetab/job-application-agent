"""Pydantic schemas — the typed contracts that flow between agents."""

from job_agent.schemas.application import ApplicationStatus, GeneratedApplication
from job_agent.schemas.job import JobPosting
from job_agent.schemas.match import MatchResult
from job_agent.schemas.profile import UserProfile

__all__ = [
    "ApplicationStatus",
    "GeneratedApplication",
    "JobPosting",
    "MatchResult",
    "UserProfile",
]
