"""MatchResult — the Matcher's verdict on a (job, profile) pair."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

BriefText = Annotated[str, Field(max_length=2_000)]

RiskLevel = Literal["low", "medium", "high"]
Recommendation = Literal["strong", "good", "maybe", "skip"]


class ScoreComponent(BaseModel):
    """One visible dimension of the explainable 1-5 match rubric."""

    key: str = Field(max_length=100, description="Stable machine key, e.g. hard_skills.")
    label: str = Field(max_length=300, description="Human-readable dimension label.")
    score: int = Field(ge=1, le=5, description="Rubric score from 1 (weak) to 5 (strong).")
    weight: int = Field(ge=0, le=100, description="Relative weight in the final score.")
    evidence: str = Field(max_length=2_000, description="Short reason shown in the UI.")

    model_config = {"extra": "forbid"}


class MatchResult(BaseModel):
    """Output of the Matcher agent.

    The Writer only runs on results with score >= the configured threshold
    (default 0.6). The rationale is shown to the user in the demo UI and is
    also fed back into the Writer as context.
    """

    job_id: str = Field(min_length=1, max_length=200)
    score: float = Field(ge=0.0, le=1.0, description="Overall match strength.")
    matched_skills: list[BriefText] = Field(
        default_factory=list,
        max_length=200,
        description="Skills present in both the posting and the profile.",
    )
    missing_skills: list[BriefText] = Field(
        default_factory=list,
        max_length=200,
        description="Required skills the candidate doesn't (yet) have.",
    )
    rationale: str = Field(
        max_length=10_000, description="2-3 sentence human-readable explanation."
    )
    score_components: list[ScoreComponent] = Field(
        default_factory=list,
        max_length=50,
        description="Explainable 1-5 rubric dimensions used for the UI breakdown.",
    )
    risk_level: RiskLevel = Field(
        default="low",
        description="Ghost-job / scam / low-quality posting risk level.",
    )
    risk_flags: list[BriefText] = Field(
        default_factory=list,
        max_length=100,
        description="Concrete warning signals found in the posting.",
    )
    recommendation: Recommendation = Field(
        default="maybe",
        description="Human-readable action bucket for the candidate.",
    )
    score_summary: str = Field(
        default="",
        max_length=2_000,
        description="One-line summary of why the score is high or low.",
    )
    evaluation_method: Literal["deterministic", "llm"] = "deterministic"
    evaluation_model: str | None = None

    model_config = {"extra": "forbid"}
