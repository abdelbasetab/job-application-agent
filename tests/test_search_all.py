"""Offline tests for the deterministic multi-board search + enrichment."""

from __future__ import annotations

from job_agent.schemas import JobPosting
from job_agent.tools import job_search


def _job(jid: str, source: str = "manual") -> JobPosting:
    url = (
        f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{jid}"
        if source == "ba-jobsuche"
        else f"https://example.de/{jid}"
    )
    return JobPosting(
        id=jid,
        source=source,
        source_id=jid,
        url=url,
        title="Role",
        company="Company",
        location="Essen",
        description="",
    )


def test_search_all_merges_and_dedups(monkeypatch):
    monkeypatch.setattr(job_search, "adzuna_search", lambda **kw: [_job("a"), _job("dup")])
    monkeypatch.setattr(job_search, "ba_jobsuche_search", lambda **kw: [_job("dup"), _job("b")])
    out = job_search.search_all("python", limit=10)
    assert [j.id for j in out] == ["a", "dup", "b"]


def test_search_all_respects_limit(monkeypatch):
    monkeypatch.setattr(job_search, "adzuna_search", lambda **kw: [_job(str(i)) for i in range(5)])
    monkeypatch.setattr(job_search, "ba_jobsuche_search", lambda **kw: [])
    out = job_search.search_all("python", limit=3)
    assert len(out) == 3


def test_extra_queries_are_deduped(monkeypatch):
    seen = []

    def fake_adzuna(**kw):
        seen.append(kw.get("query"))
        return []

    monkeypatch.setattr(job_search, "adzuna_search", fake_adzuna)
    monkeypatch.setattr(job_search, "ba_jobsuche_search", lambda **kw: [])
    job_search.search_all("python", limit=5, extra_queries=["python", "sql"])
    assert "python" in seen and "sql" in seen and seen.count("python") == 1


def test_adzuna_pages_iterated(monkeypatch):
    pages = []

    def fake_adzuna(**kw):
        pages.append(kw.get("page"))
        return []

    monkeypatch.setattr(job_search, "adzuna_search", fake_adzuna)
    monkeypatch.setattr(job_search, "ba_jobsuche_search", lambda **kw: [])
    job_search.search_all("python", limit=5, adzuna_pages=2)
    assert pages == [1, 2]


def test_enrich_fills_ba_description(monkeypatch):
    monkeypatch.setattr(job_search, "adzuna_search", lambda **kw: [])
    monkeypatch.setattr(job_search, "ba_jobsuche_search", lambda **kw: [_job("r1", "ba-jobsuche")])
    monkeypatch.setattr(job_search, "ba_jobsuche_detail", lambda refnr: "Volle Beschreibung: Python, SQL")
    out = job_search.search_all("python", limit=5, enrich=True)
    assert out[0].description == "Volle Beschreibung: Python, SQL"
    assert "Python" in out[0].requirements_raw
    assert out[0].requirements == ["python", "sql"]


def test_extract_skill_mentions_normalizes_aliases():
    requirements, nice = job_search.extract_skill_mentions(
        "Wir suchen Erfahrung mit PostgreSQL, Git und REST API. Docker ist nice to have."
    )
    assert requirements == ["sql", "git", "docker", "rest apis"]
    assert nice == ["docker"]


def test_adzuna_normalize_hydrates_requirements():
    posting = job_search._adzuna_normalize(
        {
            "id": "a1",
            "redirect_url": "https://example.de/a1",
            "title": "Python Werkstudent",
            "company": {"display_name": "Example GmbH"},
            "location": {"display_name": "Essen"},
            "description": "Python, SQL und Git fuer interne Automatisierung.",
        }
    )
    assert posting is not None
    assert posting.requirements == ["python", "sql", "git"]
