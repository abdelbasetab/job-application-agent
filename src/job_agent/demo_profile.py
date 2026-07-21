"""Shared baked-in candidate profile for demos and the web UI."""

from __future__ import annotations

from job_agent.schemas import UserProfile
from job_agent.schemas.profile import Education, Experience, Preferences


def demo_profile() -> UserProfile:
    """Return the stable demo profile used by CLI and web UI."""
    return UserProfile(
        name="Alex Beispiel",
        headline="AI Engineering Student",
        email="alex.beispiel@example.invalid",
        location="Essen, DE",
        languages={"de": "C1", "en": "C1"},
        skills=[
            "python",
            "sql",
            "git",
            "llms",
            "rag",
            "machine learning",
            "agentic workflows",
        ],
        experience=[
            Experience(
                role="AI Engineering Coursework",
                company="Beispiel-Hochschule",
                start="2025-10",
                summary="Building a multi-agent job-application system with validated tools.",
                skills_used=["python", "llms", "rag"],
            ),
        ],
        education=[
            Education(
                degree="B.Sc.",
                institution="Beispiel-Hochschule",
                field="Computer Science / AI",
                start="2023-10",
            ),
        ],
        preferences=Preferences(
            locations=["Essen", "Dortmund", "Remote"],
            remote_ok=True,
            employment_types=["working-student", "internship"],
        ),
    )
