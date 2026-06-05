from __future__ import annotations

from job_agent.agents.demo_scout import run_demo_scout
from job_agent.schemas import UserProfile
from job_agent.schemas.profile import Preferences


def test_demo_scout_returns_stable_valid_jobs() -> None:
    profile = UserProfile(
        name="Demo Candidate",
        headline="AI Student",
        email="demo@example.com",
        location="Gelsenkirchen",
        languages={"de": "C1", "en": "C1"},
        skills=["python", "sql", "git"],
        preferences=Preferences(locations=["Gelsenkirchen", "Essen", "Dortmund"]),
    )

    jobs = run_demo_scout(profile, query="Werkstudent KI", limit=5)

    assert len(jobs) == 5
    assert {job.source for job in jobs} == {"adzuna", "ba-jobsuche"}
    assert len({job.id for job in jobs}) == len(jobs)
    assert all(str(job.url).startswith("https://") for job in jobs)
