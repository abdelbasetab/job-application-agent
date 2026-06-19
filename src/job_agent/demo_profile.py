"""Shared baked-in candidate profile for demos and the web UI."""

from __future__ import annotations

from job_agent.schemas import UserProfile
from job_agent.schemas.profile import Education, Experience, Preferences


def demo_profile() -> UserProfile:
    """Return the stable demo profile used by CLI and web UI."""
    return UserProfile(
        name="Abdelbaset Abidi",
        headline="AI Engineering Student @ Westfaelische Hochschule",
        email="adessadess1990@gmail.com",
        location="Gelsenkirchen, DE",
        languages={"de": "C1", "en": "C1", "ar": "Native"},
        skills=[
            "python",
            "sql",
            "git",
            "llms",
            "rag",
            "machine learning",
            "chromadb",
        ],
        experience=[
            Experience(
                role="AI Engineering Coursework",
                company="Westfaelische Hochschule",
                start="2025-10",
                summary="Building a multi-agent job-application system with CrewAI.",
                skills_used=["python", "llms", "rag"],
            ),
        ],
        education=[
            Education(
                degree="B.Sc.",
                institution="Westfaelische Hochschule",
                field="Computer Science / AI",
                start="2023-10",
            ),
        ],
        preferences=Preferences(
            locations=["Gelsenkirchen", "Essen", "Dortmund", "Remote"],
            remote_ok=True,
            employment_types=["working-student", "internship"],
        ),
    )
