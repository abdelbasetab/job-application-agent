"""Offline tests for the web CV-upload + profile-build helpers."""

from __future__ import annotations

import base64

import pytest

from job_agent import web
from job_agent.schemas import UserProfile
from job_agent.utils.cv import validate_cv_content


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


def test_cv_magic_and_cli_suffix_validation() -> None:
    with pytest.raises(ValueError, match="PDF-Signatur"):
        validate_cv_content(b"not a pdf", ".pdf")
    with pytest.raises(ValueError, match="Dateityp"):
        validate_cv_content(b"plain text", ".exe")
    with pytest.raises(ValueError, match="binaere"):
        validate_cv_content(b"text\x00binary", ".txt")


def test_build_profile_empty_requires_explicit_demo_choice():
    with pytest.raises(ValueError, match="Demo-Profil bewusst"):
        web._build_profile_from_payload({"cv_text": ""})


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


def test_build_profile_does_not_replace_failed_cv_with_demo(monkeypatch):
    from job_agent.agents import profiler

    def boom(text):
        raise RuntimeError("no key")

    monkeypatch.setattr(profiler, "run_profiler", boom)
    state = web.WebState()
    with pytest.raises(RuntimeError, match="no key"):
        web._build_profile_from_payload({"cv_text": "Python"}, state)
    assert state.session(None).current_profile is None
