"""CVAssessment — the CV Reviewer's verdict on a candidate's Lebenslauf."""

from __future__ import annotations

from pydantic import BaseModel, Field

from job_agent.schemas.match import ScoreComponent


class CVAssessment(BaseModel):
    """Explainable quality review of a CV (Lebenslauf).

    Mirrors the Matcher's rubric style: weighted 1-5 dimensions with evidence,
    plus concrete German improvement tips. The deterministic rubric always
    works offline; ``llm_feedback`` is an optional extra paragraph from the
    configured LLM.
    """

    overall_score: float = Field(
        ge=1.0, le=5.0, description="Weighted overall CV quality, 1.0 (weak) to 5.0 (strong)."
    )
    components: list[ScoreComponent] = Field(
        default_factory=list,
        description="Explainable 1-5 rubric dimensions (contact, structure, skills, ...).",
    )
    tips: list[str] = Field(
        default_factory=list,
        description="Concrete, actionable German improvement tips (worst dimensions first).",
    )
    summary: str = Field(default="", description="One-line German verdict for the UI.")
    word_count: int = Field(ge=0, default=0, description="Words in the analyzed CV text.")
    llm_feedback: str = Field(
        default="",
        description="Optional free-text feedback from the LLM (empty when offline).",
    )

    model_config = {"extra": "forbid"}
