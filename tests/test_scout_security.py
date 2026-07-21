from __future__ import annotations

from job_agent.agents.scout import _verify_tool_postings
from job_agent.schemas import JobPosting


def _job(job_id: str, *, company: str = "ACME GmbH") -> JobPosting:
    return JobPosting(
        id=job_id,
        source="manual",
        source_id=job_id,
        url=f"https://example.de/jobs/{job_id}",
        title="Werkstudent Python",
        company=company,
        location="Essen",
        description="Python und SQL",
        requirements=["python", "sql"],
    )


def test_scout_accepts_only_exact_tool_records() -> None:
    real = _job("real")
    invented = _job("invented")
    tampered = real.model_dump(mode="json")
    tampered["company"] = "Manipulierte GmbH"

    verified = _verify_tool_postings(
        [real.model_dump(mode="json"), invented.model_dump(mode="json"), tampered],
        [real],
    )

    assert verified == [real]
