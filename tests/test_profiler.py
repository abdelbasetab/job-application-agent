"""Offline tests for the CV Profiler agent and CV/profile I/O."""

from __future__ import annotations

import json

import pytest

from job_agent.agents import profiler
from job_agent.schemas import UserProfile
from job_agent.utils import cv


def _fake_reply() -> str:
    return json.dumps(
        {
            "name": "Test Candidate",
            "headline": "Werkstudent KI",
            "email": "test@example.com",
            "location": "Essen, DE",
            "languages": {"de": "C1", "en": "B2"},
            "skills": ["Python", "SQL", "python"],  # case + duplicate
            "experience": [
                {
                    "role": "Werkstudent",
                    "company": "Acme",
                    "start": "2024-01",
                    "summary": "Worked on data",
                    "skills_used": ["python"],
                }
            ],
            "education": [
                {"degree": "B.Sc.", "institution": "WH", "field": "CS", "start": "2023-10"}
            ],
            "preferences": {
                "locations": ["Essen"],
                "remote_ok": True,
                "employment_types": ["working-student"],
            },
            "unexpected_key": "must be dropped",  # extra=forbid would reject this
        }
    )


def test_run_profiler_parses_and_normalizes(monkeypatch):
    monkeypatch.setattr(profiler, "call_llm", lambda messages, **_kw: _fake_reply())
    profile = profiler.run_profiler("some cv text")
    assert isinstance(profile, UserProfile)
    assert profile.name == "Test Candidate"
    # lowercased + deduplicated, original order preserved
    assert profile.skills == ["python", "sql"]
    assert profile.languages == {"de": "C1", "en": "B2"}


def test_run_profiler_strips_code_fences(monkeypatch):
    fenced = "```json\n" + _fake_reply() + "\n```"
    monkeypatch.setattr(profiler, "call_llm", lambda messages, **_kw: fenced)
    assert profiler.run_profiler("cv").name == "Test Candidate"


def test_run_profiler_handles_surrounding_prose(monkeypatch):
    noisy = "Here is the profile you asked for:\n" + _fake_reply() + "\nHope it helps!"
    monkeypatch.setattr(profiler, "call_llm", lambda messages, **_kw: noisy)
    assert profiler.run_profiler("cv").headline == "Werkstudent KI"


def test_run_profiler_backfills_missing_headline(monkeypatch):
    data = {
        "name": "No Headline",
        "email": "x@y.z",
        "location": "Bochum",
        "languages": {"de": "C1"},
        "skills": ["python"],
        "experience": [{"role": "Data Intern", "company": "Z", "start": "2024-01"}],
        "education": [],
    }
    monkeypatch.setattr(profiler, "call_llm", lambda messages, **_kw: json.dumps(data))
    assert profiler.run_profiler("cv").headline == "Data Intern"


def test_run_profiler_empty_text_raises():
    with pytest.raises(ValueError):
        profiler.run_profiler("   ")


def test_run_profiler_rejects_oversized_pasted_text_before_llm(monkeypatch):
    def forbidden_call(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("LLM must not be called for oversized input")

    monkeypatch.setattr(profiler, "call_llm", forbidden_call)
    with pytest.raises(ValueError, match="maximum"):
        profiler.run_profiler("x" * (cv.MAX_EXTRACTED_CHARS + 1))


def test_run_profiler_rejects_non_json(monkeypatch):
    monkeypatch.setattr(profiler, "call_llm", lambda messages, **_kw: "sorry, I cannot help")
    with pytest.raises(ValueError):
        profiler.run_profiler("cv")


def test_extract_cv_text_markdown(tmp_path):
    path = tmp_path / "cv.md"
    path.write_text("# Lebenslauf\nPython, SQL, Git", encoding="utf-8")
    assert "Python" in cv.extract_cv_text(path)


def test_extract_cv_text_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        cv.extract_cv_text(tmp_path / "nope.txt")


def test_extract_cv_text_empty(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("   \n", encoding="utf-8")
    with pytest.raises(ValueError):
        cv.extract_cv_text(path)


def test_load_profile_yaml_roundtrip(tmp_path):
    profile = UserProfile(
        name="Y",
        headline="H",
        email="e@x.de",
        location="Essen",
        languages={"de": "C1"},
        skills=["python"],
    )
    path = tmp_path / "profile.yaml"
    path.write_text(cv.profile_to_yaml(profile), encoding="utf-8")
    loaded = cv.load_profile_yaml(path)
    assert loaded.name == "Y"
    assert loaded.skills == ["python"]
