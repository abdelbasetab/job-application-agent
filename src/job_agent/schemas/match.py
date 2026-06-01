"""MatchResult — the Matcher's verdict on a (job, profile) pair."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MatchResult(BaseModel):
    """Output of the Matcher agent.

    The Writer only runs on results with score >= the configured threshold
    (default 0.6). The rationale is shown to the user in the demo UI and is
    also fed back into the Writer as context.
    """

    job_id: str
    score: float = Field(ge=0.0, le=1.0, description="Overall match strength.")
    matched_skills: list[str] = Field(
        default_factory=list,
        description="Skills present in both the posting and the profile.",
    )
    missing_skills: list[str] = Field(
        default_factory=list,
        description="Required skills the candidate doesn't (yet) have.",
    )
    rationale: str = Field(description="2-3 sentence human-readable explanation.")

    model_config = {"extra": "forbid"}
