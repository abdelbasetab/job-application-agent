"""JobPosting — the canonical representation of a single job ad."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class JobPosting(BaseModel):
    """A normalized job posting, regardless of which board it came from.

    Scout's job is to produce instances of this. Every field below must be
    populated from the source ad — Scout is *not* allowed to hallucinate
    requirements; if a field isn't in the source, leave the list empty.
    """

    id: str = Field(description="Stable hash of (source, source_id) — used for dedup.")
    source: Literal[
        "adzuna", "ba-jobsuche", "stepstone", "linkedin", "indeed", "xing", "manual"
    ]
    source_id: str = Field(description="The id assigned by the source board.")
    url: HttpUrl

    title: str
    company: str
    location: str
    posted_at: date | None = None

    description: str = Field(description="Full job description as plain text.")
    requirements_raw: str = Field(
        default="",
        description="The 'Anforderungen' / 'Requirements' block, unparsed.",
    )

    # Matcher reads these — Scout must normalize them out of requirements_raw.
    requirements: list[str] = Field(
        default_factory=list,
        description="Hard skills / must-haves, one per item, lowercased.",
    )
    nice_to_have: list[str] = Field(
        default_factory=list,
        description="Soft / preferred skills.",
    )

    salary_range: tuple[int, int] | None = None
    employment_type: (
        Literal["full-time", "part-time", "internship", "thesis", "working-student"] | None
    ) = None
    remote: bool | None = None

    model_config = {"extra": "forbid"}
