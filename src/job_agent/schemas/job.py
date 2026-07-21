"""JobPosting — the canonical representation of a single job ad."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator

RequirementText = Annotated[str, Field(max_length=2_000)]


class JobPosting(BaseModel):
    """A normalized job posting, regardless of which board it came from.

    Scout's job is to produce instances of this. Every field below must be
    populated from the source ad — Scout is *not* allowed to hallucinate
    requirements; if a field isn't in the source, leave the list empty.
    """

    id: str = Field(
        min_length=1,
        max_length=200,
        description="Stable hash of (source, source_id) — used for dedup.",
    )
    source: Literal[
        "adzuna", "ba-jobsuche", "stepstone", "linkedin", "indeed", "xing", "manual"
    ]
    source_id: str = Field(
        min_length=1, max_length=500, description="The id assigned by the source board."
    )
    url: HttpUrl

    title: str = Field(min_length=1, max_length=500)
    company: str = Field(min_length=1, max_length=500)
    location: str = Field(min_length=1, max_length=500)
    posted_at: date | None = None

    description: str = Field(
        max_length=200_000, description="Full job description as plain text."
    )
    requirements_raw: str = Field(
        default="",
        max_length=200_000,
        description="The 'Anforderungen' / 'Requirements' block, unparsed.",
    )

    # Matcher reads these — Scout must normalize them out of requirements_raw.
    requirements: list[RequirementText] = Field(
        default_factory=list,
        max_length=200,
        description="Hard skills / must-haves, one per item, lowercased.",
    )
    nice_to_have: list[RequirementText] = Field(
        default_factory=list,
        max_length=200,
        description="Soft / preferred skills.",
    )

    salary_range: tuple[int, int] | None = None
    employment_type: (
        Literal["full-time", "part-time", "internship", "thesis", "working-student"] | None
    ) = None
    remote: bool | None = None

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_salary_range(self) -> JobPosting:
        if self.salary_range is None:
            return self
        low, high = self.salary_range
        if low < 0 or high < 0:
            raise ValueError("salary_range values must be non-negative")
        if low > high:
            raise ValueError("salary_range lower bound must not exceed upper bound")
        return self
