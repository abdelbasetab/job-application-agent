"""Small stdlib web UI for the Job Application Agent."""

from __future__ import annotations

import base64
import binascii
import json
import os
import tempfile
import threading
import uuid
import webbrowser
from collections.abc import Callable
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from job_agent.agents.demo_scout import run_demo_scout
from job_agent.demo_profile import demo_profile
from job_agent.memory.store import Store
from job_agent.pipeline import PipelineResult, run_pipeline
from job_agent.schemas import (
    ApplicationStatus,
    GeneratedApplication,
    JobPosting,
    MatchResult,
    UserProfile,
)
from job_agent.utils.config import settings
from job_agent.utils.logging import get_logger

log = get_logger(__name__)

STATIC_DIR = Path(__file__).with_name("web_static")
DEFAULT_DEMO_DB = "./data/demo_job_agent.db"
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
MAX_JSON_BODY_BYTES = 12 * 1024 * 1024
MAX_CV_UPLOAD_BYTES = 8 * 1024 * 1024
ALLOWED_CV_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}
ALLOWED_DB_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
STATUS_STAGES = {"draft", "submitted", "interview", "rejected", "offer", "withdrawn"}

ProgressFn = Callable[[str, int], None]

_PROGRESS_LOCK = threading.Lock()
_PROGRESS: dict[str, dict[str, Any]] = {}


class WebState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.last_result: PipelineResult | None = None
        self.last_db_path = DEFAULT_DEMO_DB
        self.last_error: str | None = None
        self.current_profile: UserProfile | None = None
        self.current_profile_source = "demo"


def run_web_server(host: str = "127.0.0.1", port: int = 7860, open_browser: bool = False) -> None:
    """Start the local web UI server."""
    state = WebState()
    handler_cls = _build_handler(state)
    server = ThreadingHTTPServer((host, port), handler_cls)
    url = f"http://{host}:{port}"
    log.info("[web] serving Job Application Agent UI at %s", url)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("[web] shutting down")
    finally:
        server.server_close()


def _build_handler(state: WebState) -> type[BaseHTTPRequestHandler]:
    class JobAgentHandler(BaseHTTPRequestHandler):
        server_version = "JobAgentWeb/0.1"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path in ("/", "/index.html"):
                self._send_static("index.html", "text/html; charset=utf-8")
                return
            if parsed.path == "/api/state":
                self._send_json(_state_payload(state))
                return
            if parsed.path == "/api/config":
                self._send_json(_config_payload())
                return
            if parsed.path == "/api/applications":
                params = parse_qs(parsed.query)
                db_path = params.get("db_path", [state.last_db_path])[0]
                try:
                    self._send_json({"applications": _load_applications(db_path)})
                except Exception as exc:
                    self._send_json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                return
            if parsed.path == "/api/pipeline-progress":
                params = parse_qs(parsed.query)
                self._send_json(_pipeline_progress(params.get("id", [""])[0]))
                return
            if parsed.path.startswith("/static/"):
                rel_path = parsed.path.removeprefix("/static/")
                content_type = _content_type(rel_path)
                self._send_static(rel_path, content_type)
                return
            self._send_error(HTTPStatus.NOT_FOUND, "Not found")

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/extract-cv":
                try:
                    payload = self._read_json()
                    response = _extract_cv_from_payload(payload)
                except Exception as exc:
                    log.exception("[web] CV extraction failed")
                    self._send_json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                    )
                    return
                self._send_json(response)
                return
            if parsed.path == "/api/build-profile":
                try:
                    payload = self._read_json()
                    response = _build_profile_from_payload(payload, state)
                except Exception as exc:
                    log.exception("[web] profile build failed")
                    self._send_json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                    )
                    return
                self._send_json(response)
                return
            if parsed.path == "/api/use-demo-profile":
                self._send_json(_use_demo_profile(state))
                return
            if parsed.path == "/api/update-status":
                try:
                    payload = self._read_json()
                    response = _update_status_from_payload(payload, state)
                except Exception as exc:
                    log.exception("[web] status update failed")
                    self._send_json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                self._send_json(response)
                return
            if parsed.path == "/api/send-application-email":
                try:
                    payload = self._read_json()
                    response = _send_application_email_from_payload(payload, state)
                except Exception as exc:
                    log.exception("[web] email submission failed")
                    self._send_json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                self._send_json(response)
                return
            if parsed.path == "/api/run-pipeline-async":
                try:
                    payload = self._read_json()
                    response = _start_pipeline_async(payload, state)
                except Exception as exc:
                    log.exception("[web] async pipeline start failed")
                    self._send_json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                    )
                    return
                self._send_json(response)
                return
            if parsed.path != "/api/run-pipeline":
                self._send_error(HTTPStatus.NOT_FOUND, "Not found")
                return
            try:
                payload = self._read_json()
                response = _run_pipeline_from_payload(payload, state)
            except Exception as exc:
                log.exception("[web] pipeline request failed")
                with state.lock:
                    state.last_error = str(exc)
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self._send_json(response)

        def log_message(self, format: str, *args: Any) -> None:
            log.info("[web] " + format, *args)

        def _read_json(self) -> dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise ValueError("Invalid Content-Length header") from None
            if length > MAX_JSON_BODY_BYTES:
                raise ValueError(
                    f"Request body too large. Maximum is {MAX_JSON_BODY_BYTES // (1024 * 1024)} MB."
                )
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Request body must be a JSON object")
            return data

        def _send_static(self, rel_path: str, content_type: str) -> None:
            path = (STATIC_DIR / rel_path).resolve()
            static_root = STATIC_DIR.resolve()
            if static_root not in path.parents and path != static_root:
                self._send_error(HTTPStatus.FORBIDDEN, "Forbidden")
                return
            if not path.exists() or not path.is_file():
                self._send_error(HTTPStatus.NOT_FOUND, "Not found")
                return
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_error(self, status: HTTPStatus, message: str) -> None:
            self._send_json({"ok": False, "error": message}, status=status)

    return JobAgentHandler


def _extract_cv_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Decode an uploaded CV file (base64), extract its text, and return it."""
    from job_agent.utils.cv import extract_cv_text

    filename = str(payload.get("filename") or "cv.txt")
    content_b64 = str(payload.get("content_base64") or "")
    if not content_b64:
        raise ValueError("No file content received.")
    try:
        raw = base64.b64decode(content_b64, validate=True)
    except binascii.Error:
        raise ValueError("Uploaded file content is not valid base64.") from None
    if len(raw) > MAX_CV_UPLOAD_BYTES:
        raise ValueError(
            f"CV file is too large. Maximum is {MAX_CV_UPLOAD_BYTES // (1024 * 1024)} MB."
        )
    suffix = (Path(filename).suffix or ".txt").lower()
    if suffix not in ALLOWED_CV_SUFFIXES:
        allowed = ", ".join(sorted(ALLOWED_CV_SUFFIXES))
        raise ValueError(f"Unsupported CV file type '{suffix}'. Allowed: {allowed}.")

    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
        text = extract_cv_text(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    log.info("[web] extracted %d chars from uploaded %s", len(text), filename)
    return {"ok": True, "filename": filename, "chars": len(text), "cv_text": text}


def _profile_dump(profile: UserProfile) -> dict[str, Any]:
    return profile.model_dump(mode="json")


def _build_profile_from_payload(
    payload: dict[str, Any], state: WebState | None = None
) -> dict[str, Any]:
    """Build a structured profile from CV text for on-screen verification.

    With CV text the LLM Profiler extracts a real UserProfile; without text (or
    when the LLM is unavailable) the demo profile is returned, clearly flagged.
    """
    cv_text = str(payload.get("cv_text") or "").strip()
    if cv_text:
        try:
            from job_agent.agents.profiler import run_profiler

            profile = run_profiler(cv_text)
            if state is not None:
                with state.lock:
                    state.current_profile = profile
                    state.current_profile_source = "cv"
            return {"ok": True, "source": "cv", "profile": _profile_dump(profile)}
        except Exception as exc:
            log.warning("[web] profiler failed, showing demo preview: %s", exc)
            profile = demo_profile()
            if state is not None:
                with state.lock:
                    state.current_profile = profile
                    state.current_profile_source = "demo"
            return {
                "ok": True,
                "source": "demo",
                "warning": (
                    f"KI-Connect/LLM nicht erreichbar ({exc}). Vorschau mit "
                    "Demo-Daten - setze LLM_BASE_URL + OPENAI_API_KEY in .env "
                    "fuer dein echtes Profil."
                ),
                "profile": _profile_dump(profile),
            }
    profile = demo_profile()
    if state is not None:
        with state.lock:
            state.current_profile = profile
            state.current_profile_source = "demo"
    return {"ok": True, "source": "demo", "profile": _profile_dump(profile)}


def _use_demo_profile(state: WebState) -> dict[str, Any]:
    profile = demo_profile()
    with state.lock:
        state.current_profile = profile
        state.current_profile_source = "demo"
    return {"ok": True, "source": "demo", "profile": _profile_dump(profile)}


def _run_pipeline_from_payload(
    payload: dict[str, Any],
    state: WebState,
    progress: ProgressFn | None = None,
) -> dict[str, Any]:
    demo = bool(payload.get("demo", True))
    query = str(payload.get("query") or "Werkstudent KI")
    limit = _bounded_int(payload.get("limit"), default=5, minimum=1, maximum=25)
    threshold = _bounded_float(payload.get("threshold"), default=0.5, minimum=0.0, maximum=1.0)
    draft_all = bool(payload.get("draft_all", False))
    use_llm = bool(payload.get("llm_agents", False))
    use_chroma = bool(payload.get("chroma", False))
    reset_db = bool(payload.get("reset_db", False))
    db_path = _resolve_db_path(
        str(payload.get("db_path") or (DEFAULT_DEMO_DB if demo else settings.sqlite_path))
    )

    if reset_db:
        if db_path.exists():
            db_path.unlink()

    cv_text = str(payload.get("cv_text") or "").strip()
    force_demo_profile = bool(payload.get("force_demo_profile", False))
    used_cv = False
    if force_demo_profile:
        profile = demo_profile()
        profile_source = "demo"
        with state.lock:
            state.current_profile = profile
            state.current_profile_source = profile_source
    elif cv_text:
        from job_agent.agents.profiler import run_profiler

        if progress is not None:
            progress("Profil aus CV erstellen", 5)
        log.info("[web] building profile from pasted CV (%d chars)", len(cv_text))
        profile = run_profiler(cv_text)
        used_cv = True
        profile_source = "cv"
        with state.lock:
            state.current_profile = profile
            state.current_profile_source = profile_source
    else:
        with state.lock:
            current_profile = state.current_profile
            current_profile_source = state.current_profile_source
        if current_profile is not None:
            profile = current_profile
            profile_source = current_profile_source
            used_cv = profile_source == "cv"
        else:
            profile = demo_profile()
            profile_source = "demo"
    store = Store(db_path)
    try:
        scout_runner = run_demo_scout
        if not demo:
            from job_agent.agents.scout import run_scout

            scout_runner = run_scout

        result = run_pipeline(
            profile=profile,
            store=store,
            query=query,
            match_threshold=0.0 if draft_all else threshold,
            job_limit=limit,
            scout_runner=scout_runner,
            use_llm_agents=use_llm,
            use_chroma=use_chroma,
            progress=progress,
        )
        statuses = store.all_status()
        applications = [app for status in statuses if (app := store.get_application(status.job_id))]
    finally:
        store.close()

    with state.lock:
        state.last_result = result
        state.last_db_path = str(db_path)
        state.last_error = None

    return {
        "ok": True,
        "db_path": str(db_path),
        "profile": {
            "name": profile.name,
            "headline": profile.headline,
            "skills": profile.skills,
            "from_cv": used_cv,
            "source": profile_source,
        },
        "draft_all": draft_all,
        "summary": _summary_payload(result),
        "jobs": [_job_payload(job, result.matches, statuses) for job in result.jobs],
        "applications": [_application_payload(app, statuses) for app in applications],
    }


def _start_pipeline_async(payload: dict[str, Any], state: WebState) -> dict[str, Any]:
    """Run the pipeline in a background thread, tracking progress by job id."""
    job_id = uuid.uuid4().hex
    with _PROGRESS_LOCK:
        if len(_PROGRESS) > 40:
            for old in list(_PROGRESS)[:20]:
                _PROGRESS.pop(old, None)
        _PROGRESS[job_id] = {
            "stage": "Start",
            "percent": 0,
            "done": False,
            "result": None,
            "error": None,
        }

    def worker() -> None:
        def progress(stage: str, percent: int) -> None:
            with _PROGRESS_LOCK:
                entry = _PROGRESS.get(job_id)
                if entry is not None:
                    entry["stage"] = stage
                    entry["percent"] = percent

        try:
            result = _run_pipeline_from_payload(payload, state, progress=progress)
            with _PROGRESS_LOCK:
                _PROGRESS[job_id].update(result=result, done=True, percent=100, stage="Fertig")
        except Exception as exc:
            log.exception("[web] async pipeline failed")
            with _PROGRESS_LOCK:
                _PROGRESS[job_id].update(error=str(exc), done=True, stage="Fehler")

    threading.Thread(target=worker, daemon=True).start()
    return {"ok": True, "job_id": job_id}


def _pipeline_progress(job_id: str) -> dict[str, Any]:
    with _PROGRESS_LOCK:
        entry = _PROGRESS.get(job_id)
        if entry is None:
            return {"ok": False, "error": "unknown job_id"}
        out: dict[str, Any] = {
            "ok": True,
            "stage": entry["stage"],
            "percent": entry["percent"],
            "done": entry["done"],
            "error": entry["error"],
        }
        if entry["done"]:
            out["result"] = entry["result"]
            _PROGRESS.pop(job_id, None)
        return out


def _state_payload(state: WebState) -> dict[str, Any]:
    with state.lock:
        result = state.last_result
        db_path = state.last_db_path
        error = state.last_error
        current_profile = state.current_profile
        current_profile_source = state.current_profile_source
    payload: dict[str, Any] = {"ok": error is None, "db_path": db_path, "error": error}
    if current_profile is not None:
        payload["profile"] = {
            "name": current_profile.name,
            "headline": current_profile.headline,
            "skills": current_profile.skills,
            "source": current_profile_source,
            "from_cv": current_profile_source == "cv",
        }
    if result is not None:
        statuses = _safe_statuses(db_path)
        payload["summary"] = _summary_payload(result)
        payload["jobs"] = [_job_payload(job, result.matches, statuses) for job in result.jobs]
        payload["applications"] = _load_applications(db_path)
    return payload


def _config_payload() -> dict[str, Any]:
    return {
        "ok": True,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "embedding_model": settings.embedding_model,
        "email_dry_run": settings.email_dry_run,
        "email_demo_recipient": settings.email_demo_recipient or "",
        "email_ready": settings.email_dry_run
        or bool(settings.email_smtp_host and (settings.email_from or settings.email_smtp_user)),
        "llm_agents_default": settings.enable_llm_agents,
        "chroma_default": settings.enable_chroma,
        "max_cv_upload_mb": MAX_CV_UPLOAD_BYTES // (1024 * 1024),
        "default_demo_db": str(_resolve_db_path(DEFAULT_DEMO_DB)),
        "default_live_db": str(_resolve_db_path(settings.sqlite_path)),
    }


def _load_applications(db_path: str) -> list[dict[str, Any]]:
    store = Store(_resolve_db_path(db_path))
    try:
        statuses = store.all_status()
        return [
            _application_payload(app, statuses)
            for status in statuses
            if (app := store.get_application(status.job_id))
        ]
    finally:
        store.close()


def _update_status_from_payload(payload: dict[str, Any], state: WebState) -> dict[str, Any]:
    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("job_id is required")

    status = str(payload.get("status") or "draft").strip()
    if status not in STATUS_STAGES:
        allowed = ", ".join(sorted(STATUS_STAGES))
        raise ValueError(f"Unknown status '{status}'. Allowed: {allowed}.")

    notes = str(payload.get("notes") or "")[:1000]
    db_path = _resolve_db_path(str(payload.get("db_path") or state.last_db_path))
    store = Store(db_path)
    try:
        existing = store.get_status(job_id)
        submitted_at = existing.submitted_at if existing else None
        if status == "submitted" and submitted_at is None:
            submitted_at = datetime.now()
        record = ApplicationStatus(
            job_id=job_id,
            status=status,  # type: ignore[arg-type]
            submitted_at=submitted_at,
            updated_at=datetime.now(),
            notes=notes if notes else (existing.notes if existing else ""),
        )
        store.upsert_status(record)
        statuses = store.all_status()
        applications = [
            _application_payload(app, statuses)
            for item in statuses
            if (app := store.get_application(item.job_id))
        ]
    finally:
        store.close()

    with state.lock:
        state.last_db_path = str(db_path)

    return {
        "ok": True,
        "status": record.model_dump(mode="json"),
        "applications": applications,
    }


def _send_application_email_from_payload(payload: dict[str, Any], state: WebState) -> dict[str, Any]:
    from job_agent.tools.email_delivery import send_application_email

    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("job_id is required")

    recipient = str(payload.get("recipient") or "").strip() or None
    db_path = _resolve_db_path(str(payload.get("db_path") or state.last_db_path))
    store = Store(db_path)
    try:
        job = store.get_job(job_id)
        application = store.get_application(job_id)
        if job is None:
            raise ValueError(f"Job '{job_id}' not found in store.")
        if application is None:
            raise ValueError(f"No drafted application exists for job '{job_id}'.")

        email_result = send_application_email(job, application, recipient=recipient)
        existing = store.get_status(job_id)
        submitted_at = existing.submitted_at if existing else None
        status = existing.status if existing else "draft"
        if email_result["sent"]:
            status = "submitted"
            if submitted_at is None:
                submitted_at = datetime.now()
        event = (
            f"E-Mail gesendet an {email_result['recipient']}."
            if email_result["sent"]
            else f"E-Mail Dry-run vorbereitet an {email_result['recipient']}."
        )
        notes = _append_note(existing.notes if existing else "", event)
        record = ApplicationStatus(
            job_id=job_id,
            status=status,
            submitted_at=submitted_at,
            updated_at=datetime.now(),
            notes=notes,
        )
        store.upsert_status(record)
        statuses = store.all_status()
        applications = [
            _application_payload(app, statuses)
            for item in statuses
            if (app := store.get_application(item.job_id))
        ]
    finally:
        store.close()

    with state.lock:
        state.last_db_path = str(db_path)

    return {
        "ok": True,
        "email": email_result,
        "status": record.model_dump(mode="json"),
        "applications": applications,
    }


def _append_note(existing: str, event: str) -> str:
    merged = f"{existing}\n{event}".strip() if existing else event
    return merged[-1000:]


def _safe_statuses(db_path: str) -> list[ApplicationStatus]:
    try:
        store = Store(_resolve_db_path(db_path))
        try:
            return store.all_status()
        finally:
            store.close()
    except Exception:
        return []


def _resolve_db_path(db_path: str) -> Path:
    """Resolve user-supplied SQLite paths into the project data directory."""
    raw_path = Path(db_path).expanduser()
    candidate = raw_path if raw_path.is_absolute() else REPO_ROOT / raw_path
    resolved = candidate.resolve(strict=False)
    data_root = DATA_DIR.resolve(strict=False)

    if resolved != data_root and data_root not in resolved.parents:
        raise ValueError("Database path must stay inside the project data directory.")
    if resolved.suffix.lower() not in ALLOWED_DB_SUFFIXES:
        raise ValueError("Database path must end with .db, .sqlite, or .sqlite3.")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def _summary_payload(result: PipelineResult) -> dict[str, int]:
    return {
        "jobs": len(result.jobs),
        "matches": len(result.matches),
        "drafts": len(result.applications),
        "tracked": len(result.statuses),
    }


def _job_payload(
    job: JobPosting,
    matches: list[MatchResult],
    statuses: list[ApplicationStatus],
) -> dict[str, Any]:
    match = next((item for item in matches if item.job_id == job.id), None)
    status = next((item for item in statuses if item.job_id == job.id), None)
    return {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "source": job.source,
        "url": str(job.url),
        "remote": job.remote,
        "employment_type": job.employment_type,
        "salary_range": job.salary_range,
        "requirements": job.requirements,
        "nice_to_have": job.nice_to_have,
        "description": job.description,
        "score": match.score if match else None,
        "score_explanation": _score_explanation(job, match),
        "matched_skills": match.matched_skills if match else [],
        "missing_skills": match.missing_skills if match else [],
        "rationale": match.rationale if match else "",
        "status": status.status if status else None,
    }


def _application_payload(
    app: GeneratedApplication,
    statuses: list[ApplicationStatus],
) -> dict[str, Any]:
    status = next((item for item in statuses if item.job_id == app.job_id), None)
    return {
        "job_id": app.job_id,
        "status": status.status if status else "draft",
        "submitted_at": status.submitted_at.isoformat() if status and status.submitted_at else None,
        "updated_at": status.updated_at.isoformat() if status else None,
        "notes": status.notes if status else "",
        "cover_letter_md": app.cover_letter_md,
        "quality_checks": app.quality_checks,
    }


def _score_explanation(job: JobPosting, match: MatchResult | None) -> str:
    if match is None:
        return "Noch nicht bewertet."
    required = len(job.requirements)
    matched = len(match.matched_skills)
    rationale = match.rationale.lower()
    nice_hit = "nice-to-have" in rationale and "bonus" in rationale
    if required:
        base = f"{matched}/{required} erkannte Muss-Skills passen"
    else:
        base = "Keine strukturierten Muss-Skills im Inserat erkannt"
    bonus = " plus Nice-to-have-Bonus" if nice_hit else ""
    return f"{base}{bonus}. Score: {match.score:.2f}."


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _bounded_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _content_type(path: str) -> str:
    if path.endswith(".css"):
        return "text/css; charset=utf-8"
    if path.endswith(".js"):
        return "application/javascript; charset=utf-8"
    if path.endswith(".html"):
        return "text/html; charset=utf-8"
    return "application/octet-stream"
