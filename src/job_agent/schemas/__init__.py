"""Pydantic schemas — the typed contracts that flow between agents."""

from job_agent.schemas.application import ApplicationStatus, FollowUpItem, GeneratedApplication
from job_agent.schemas.job import JobPosting
from job_agent.schemas.liveness import CheckedVia, LivenessResult, LivenessStatus
from job_agent.schemas.match import MatchResult, Recommendation, RiskLevel, ScoreComponent
from job_agent.schemas.profile import UserProfile
from job_agent.schemas.review import CVAssessment

__all__ = [
    "ApplicationStatus",
    "CVAssessment",
    "CheckedVia",
    "FollowUpItem",
    "GeneratedApplication",
    "JobPosting",
    "LivenessResult",
    "LivenessStatus",
    "MatchResult",
    "Recommendation",
    "RiskLevel",
    "ScoreComponent",
    "UserProfile",
]
