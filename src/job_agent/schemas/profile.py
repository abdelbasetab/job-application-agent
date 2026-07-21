"""UserProfile — the candidate's normalized CV + preferences."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

ShortText = Annotated[str, Field(max_length=500)]
LongText = Annotated[str, Field(max_length=50_000)]
EmailText = Annotated[str, Field(max_length=254)]


class Experience(BaseModel):
    role: ShortText
    company: ShortText
    start: ShortText  # ISO date or "YYYY-MM"
    end: ShortText | None = None  # None = current
    summary: LongText = ""
    skills_used: list[ShortText] = Field(default_factory=list, max_length=200)

    model_config = {"extra": "forbid"}


class Education(BaseModel):
    degree: ShortText
    institution: ShortText
    field: ShortText
    start: ShortText
    end: ShortText | None = None
    grade: ShortText | None = None

    model_config = {"extra": "forbid"}


class Preferences(BaseModel):
    locations: list[ShortText] = Field(default_factory=list, max_length=100)
    remote_ok: bool = True
    employment_types: list[ShortText] = Field(default_factory=list, max_length=20)
    min_salary: int | None = Field(default=None, ge=0, le=10_000_000)
    excluded_companies: list[ShortText] = Field(default_factory=list, max_length=100)

    model_config = {"extra": "forbid"}


class UserProfile(BaseModel):
    """The user's CV as a structured object. Loaded from data/profile.yaml."""

    name: ShortText
    headline: ShortText
    email: EmailText
    phone: ShortText | None = None
    location: ShortText
    languages: dict[ShortText, ShortText] = Field(
        description="ISO-like language code → CEFR level, e.g. {'de': 'C1', 'en': 'C1'}.",
        max_length=50,
    )
    skills: list[ShortText] = Field(
        description="Flat list of normalized skill names.", max_length=500
    )
    experience: list[Experience] = Field(default_factory=list, max_length=100)
    education: list[Education] = Field(default_factory=list, max_length=100)
    preferences: Preferences = Field(default_factory=Preferences)

    model_config = {"extra": "forbid"}
