"""Application schemas — Writer output and Tracker state."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class GeneratedApplication(BaseModel):
    """Output of the Writer agent — the tailored application artifact."""

    job_id: str
    cover_letter_md: str = Field(description="Cover letter in Markdown, German.")
    tailored_cv_path: str | None = Field(
        default=None,
        description="Path to the CV variant for this job, if generated.",
    )
    generated_at: date = Field(default_factory=date.today)
    quality_checks: dict[str, bool] = Field(
        default_factory=dict,
        description="Self-check flags: name_correct, no_placeholders, length_ok, ...",
    )

    model_config = {"extra": "forbid"}


ApplicationStage = Literal[
    "draft",
    "submitted",
    "interview",
    "rejected",
    "offer",
    "withdrawn",
]


class ApplicationStatus(BaseModel):
    """The Tracker's persistent state for one application."""

    job_id: str
    status: ApplicationStage = "draft"
    submitted_at: datetime | None = None
    updated_at: datetime = Field(default_factory=datetime.now)
    notes: str = ""

    model_config = {"extra": "forbid"}
