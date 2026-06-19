"""Offline tests for the web CV-upload + profile-build helpers."""

from __future__ import annotations

import base64

import pytest

from job_agent import web
from job_agent.schemas import UserProfile


def test_extract_cv_from_payload_text():
    raw = b"# CV\nPython, SQL, Git"
    payload = {"filename": "cv.md", "content_base64": base64.b64encode(raw).decode()}
    out = web._extract_cv_from_payload(payload)
    assert out["ok"] is True
    assert out["filename"] == "cv.md"
    assert "Python" in out["cv_text"]
    assert out["chars"] == len(out["cv_text"])


def test_extract_cv_from_payload_empty_raises():
    with pytest.raises(ValueError):
        web._extract_cv_from_payload({"filename": "cv.txt", "content_base64": ""})


def test_extract_cv_rejects_invalid_base64():
    with pytest.raises(ValueError, match="base64"):
        web._extract_cv_from_payload({"filename": "cv.txt", "content_base64": "not-base64!"})


def test_extract_cv_rejects_unsupported_suffix():
    raw = base64.b64encode(b"hello").decode()
    with pytest.raises(ValueError, match="Unsupported CV file type"):
        web._extract_cv_from_payload({"filename": "cv.exe", "content_base64": raw})


def test_extract_cv_rejects_large_upload(monkeypatch):
    monkeypatch.setattr(web, "MAX_CV_UPLOAD_BYTES", 2)
    raw = base64.b64encode(b"toolarge").decode()
    with pytest.raises(ValueError, match="too large"):
        web._extract_cv_from_payload({"filename": "cv.txt", "content_base64": raw})


def test_build_profile_empty_returns_demo():
    out = web._build_profile_from_payload({"cv_text": ""})
    assert out["ok"] is True
    assert out["source"] == "demo"
    assert out["profile"]["name"]


def test_build_profile_from_cv(monkeypatch):
    from job_agent.agents import profiler

    fake = UserProfile(
        name="X",
        headline="H",
        email="e@x.de",
        location="Essen",
        languages={"de": "C1"},
        skills=["python"],
    )
    monkeypatch.setattr(profiler, "run_profiler", lambda text: fake)
    out = web._build_profile_from_payload({"cv_text": "Python developer"})
    assert out["source"] == "cv"
    assert out["profile"]["skills"] == ["python"]


def test_build_profile_falls_back_to_demo_on_llm_error(monkeypatch):
    from job_agent.agents import profiler

    def boom(text):
        raise RuntimeError("no key")

    monkeypatch.setattr(profiler, "run_profiler", boom)
    out = web._build_profile_from_payload({"cv_text": "Python"})
    assert out["ok"] is True
    assert out["source"] == "demo"
    assert "warning" in out
