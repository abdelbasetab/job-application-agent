"""UserProfile — the candidate's normalized CV + preferences."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Experience(BaseModel):
    role: str
    company: str
    start: str  # ISO date or "YYYY-MM"
    end: str | None = None  # None = current
    summary: str = ""
    skills_used: list[str] = Field(default_factory=list)


class Education(BaseModel):
    degree: str
    institution: str
    field: str
    start: str
    end: str | None = None
    grade: str | None = None


class Preferences(BaseModel):
    locations: list[str] = Field(default_factory=list)
    remote_ok: bool = True
    employment_types: list[str] = Field(default_factory=list)
    min_salary: int | None = None
    excluded_companies: list[str] = Field(default_factory=list)


class UserProfile(BaseModel):
    """The user's CV as a structured object. Loaded from data/profile.yaml."""

    name: str
    headline: str
    email: str
    phone: str | None = None
    location: str
    languages: dict[str, str] = Field(
        description="ISO-like language code → CEFR level, e.g. {'de': 'C1', 'en': 'C1'}.",
    )
    skills: list[str] = Field(description="Flat list of normalized skill names.")
    experience: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    preferences: Preferences = Field(default_factory=Preferences)

    model_config = {"extra": "forbid"}
