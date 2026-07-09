"""PDF/export package: rendering, sanitising, and the web export/download flow."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from job_agent import web
from job_agent.agents.demo_scout import run_demo_scout
from job_agent.agents.matcher import run_matcher
from job_agent.agents.writer import run_writer
from job_agent.demo_profile import demo_profile
from job_agent.tools.export import _latin1, _safe_slug, export_application


def _artifacts() -> tuple:  # type: ignore[type-arg]
    profile = demo_profile()
    job = run_demo_scout(profile, None, 1)[0]
    match = run_matcher([job], profile, use_llm=False)[0]
    application = run_writer(job=job, match=match, profile=profile, use_llm=False)
    return job, application, profile, match


def test_export_application_writes_pdfs_and_zip(tmp_path: Path) -> None:
    job, application, profile, match = _artifacts()
    result = export_application(job, application, profile, out_dir=tmp_path, match=match)

    assert (tmp_path / "anschreiben.pdf").read_bytes()[:4] == b"%PDF"
    assert (tmp_path / "lebenslauf.pdf").read_bytes()[:4] == b"%PDF"
    assert (tmp_path / "job_snapshot.json").exists()
    assert (tmp_path / result.zip_name).read_bytes()[:2] == b"PK"
    assert set(result.files) == {"anschreiben.pdf", "lebenslauf.pdf", "job_snapshot.json"}


def test_latin1_sanitises_unsupported_but_keeps_umlauts() -> None:
    assert _latin1(chr(0x20AC)) == "EUR"
    assert _latin1(chr(0x2014)) == "-"
    assert _latin1("Müller & Söhne") == "Müller & Söhne"


def test_safe_slug() -> None:
    assert _safe_slug("ba-jobsuche/123 abc") == "ba-jobsuche-123-abc"
    assert _safe_slug("///") == "job"


def test_web_export_and_download_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    state = web.WebState()
    resp = web._run_pipeline_from_payload(
        {
            "demo": True,
            "limit": 1,
            "draft_all": True,
            "reset_db": True,
            "db_path": str(tmp_path / "data" / "exp.db"),
        },
        state,
    )
    job_id = resp["jobs"][0]["id"]

    out = web._export_application_from_payload({"db_path": resp["db_path"], "job_id": job_id}, state)
    assert out["ok"] is True
    assert out["zip_name"].endswith(".zip")
    assert out["download"].startswith("/api/download?")

    path = web._download_path(None, job_id, out["zip_name"])
    assert path.is_file()
    assert path.read_bytes()[:2] == b"PK"


def test_web_export_uses_uploaded_cv_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    state = web.WebState()
    resp = web._run_pipeline_from_payload(
        {
            "demo": True,
            "limit": 1,
            "draft_all": True,
            "reset_db": True,
            "db_path": str(tmp_path / "data" / "exp_uploaded_cv.db"),
        },
        state,
    )
    upload_dir = tmp_path / "data" / "uploads"
    upload_dir.mkdir(parents=True)
    uploaded = upload_dir / "lebenslauf_upload.pdf"
    uploaded.write_bytes(b"%PDF-user-upload")
    with state.lock:
        state.session(None).uploaded_cv_path = str(uploaded)
    job_id = resp["jobs"][0]["id"]

    out = web._export_application_from_payload({"db_path": resp["db_path"], "job_id": job_id}, state)
    cv_path = web._output_dir(None, job_id) / "lebenslauf.pdf"

    assert cv_path.read_bytes() == b"%PDF-user-upload"
    with zipfile.ZipFile(web._output_dir(None, job_id) / out["zip_name"]) as archive:
        assert archive.read("lebenslauf.pdf") == b"%PDF-user-upload"


def test_download_path_rejects_bad_suffix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    with pytest.raises(ValueError, match="Unsupported"):
        web._download_path(None, "job-1", "secrets.env")


def test_download_path_strips_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "data")
    # Traversal is reduced to a basename inside the user's dir, then 404s.
    with pytest.raises(FileNotFoundError):
        web._download_path(None, "job-1", "../../evil.zip")
