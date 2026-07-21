"""Application schemas — Writer output and Tracker state."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class GeneratedApplication(BaseModel):
    """Output of the Writer agent — the tailored application artifact."""

    job_id: str = Field(min_length=1, max_length=200)
    cover_letter_md: str = Field(
        max_length=100_000, description="Cover letter in Markdown, German."
    )
    tailored_cv_path: str | None = Field(
        default=None,
        description="Path to the CV variant for this job, if generated.",
    )
    generated_at: date = Field(default_factory=date.today)
    quality_checks: dict[str, bool] = Field(
        default_factory=dict,
        max_length=100,
        description="Self-check flags: name_correct, no_placeholders, length_ok, ...",
    )
    generation_method: Literal["template", "llm"] = "template"
    generation_model: str | None = None

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

    job_id: str = Field(min_length=1, max_length=200)
    status: ApplicationStage = "draft"
    submitted_at: datetime | None = None
    updated_at: datetime = Field(default_factory=datetime.now)
    notes: str = Field(default="", max_length=50_000)

    model_config = {"extra": "forbid"}


class FollowUpItem(BaseModel):
    """A submitted application that is due for a polite follow-up nudge.

    Computed by the Tracker from persisted statuses — nothing is stored; the
    clock resets whenever ``updated_at`` changes (e.g. after recording a
    follow-up or any status change).
    """

    job_id: str = Field(min_length=1, max_length=200)
    title: str = Field(default="", max_length=500)
    company: str = Field(default="", max_length=500)
    status: ApplicationStage = "submitted"
    submitted_at: datetime | None = None
    last_activity: datetime
    days_since_activity: int = Field(ge=0)
    days_overdue: int = Field(ge=0, description="Days past the follow-up window.")
    suggested_email_md: str = Field(
        default="",
        max_length=100_000,
        description="Ready-to-send German follow-up email draft (Markdown).",
    )

    model_config = {"extra": "forbid"}
