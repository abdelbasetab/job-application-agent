"""MatchResult — the Matcher's verdict on a (job, profile) pair."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RiskLevel = Literal["low", "medium", "high"]
Recommendation = Literal["strong", "good", "maybe", "skip"]


class ScoreComponent(BaseModel):
    """One visible dimension of the explainable 1-5 match rubric."""

    key: str = Field(description="Stable machine key, e.g. hard_skills.")
    label: str = Field(description="Human-readable dimension label.")
    score: int = Field(ge=1, le=5, description="Rubric score from 1 (weak) to 5 (strong).")
    weight: int = Field(ge=0, le=100, description="Relative weight in the final score.")
    evidence: str = Field(description="Short reason shown in the UI.")

    model_config = {"extra": "forbid"}


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
    score_components: list[ScoreComponent] = Field(
        default_factory=list,
        description="Explainable 1-5 rubric dimensions used for the UI breakdown.",
    )
    risk_level: RiskLevel = Field(
        default="low",
        description="Ghost-job / scam / low-quality posting risk level.",
    )
    risk_flags: list[str] = Field(
        default_factory=list,
        description="Concrete warning signals found in the posting.",
    )
    recommendation: Recommendation = Field(
        default="maybe",
        description="Human-readable action bucket for the candidate.",
    )
    score_summary: str = Field(
        default="",
        description="One-line summary of why the score is high or low.",
    )

    model_config = {"extra": "forbid"}
