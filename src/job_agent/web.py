"""Small stdlib web UI for the Job Application Agent."""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import os
import secrets
import tempfile
import threading
import time
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
from job_agent.memory.auth_store import AuthStore, AuthUser
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
# Writable data root. Override with JOB_AGENT_DATA_DIR when the package is
# pip-installed or containerised (e.g. a mounted /data volume).
DATA_DIR = Path(os.getenv("JOB_AGENT_DATA_DIR") or (REPO_ROOT / "data")).resolve()
AUTH_DB_PATH = DATA_DIR / "auth.db"
AUTH_COOKIE = "job_agent_session"
CSRF_COOKIE = "job_agent_csrf"
AUTH_COOKIE_MAX_AGE = 7 * 24 * 60 * 60
# Login/registration abuse throttling (per process, in-memory).
_AUTH_RATE_LOCK = threading.Lock()
_AUTH_ATTEMPTS: dict[str, list[float]] = {}
_LOGIN_MAX_ATTEMPTS = 12
_REGISTER_MAX_ATTEMPTS = 30
_AUTH_RATE_WINDOW = 300.0
MAX_JSON_BODY_BYTES = 12 * 1024 * 1024
MAX_CV_UPLOAD_BYTES = 8 * 1024 * 1024
ALLOWED_CV_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}
ALLOWED_DB_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
STATUS_STAGES = {"draft", "submitted", "interview", "rejected", "offer", "withdrawn"}

ProgressFn = Callable[[str, int], None]

_PROGRESS_LOCK = threading.Lock()
_PROGRESS: dict[str, dict[str, Any]] = {}


def _user_data_dir(user_id: int) -> Path:
    """Per-user data root. Each account's pipeline data lives here, isolated."""
    root = (DATA_DIR / "users" / str(int(user_id))).resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    return root


class _UserSession:
    """In-memory working state scoped to a single authenticated user."""

    def __init__(self, default_db: str) -> None:
        self.last_result: PipelineResult | None = None
        self.last_db_path = default_db
        self.last_error: str | None = None
        self.current_profile: UserProfile | None = None
        self.current_profile_source = "demo"


class WebState:
    """Server-wide state: one isolated :class:`_UserSession` per account.

    Requests with no authenticated user (direct unit-test calls, single-user
    local use) share a default session whose data stays under ``DATA_DIR``.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self._default = _UserSession(DEFAULT_DEMO_DB)
        self._users: dict[int, _UserSession] = {}

    def session(self, user: AuthUser | None) -> _UserSession:
        """Return the working session for ``user`` (creating it on first use)."""
        if user is None:
            return self._default
        uid = int(user["id"])
        with self.lock:
            sess = self._users.get(uid)
            if sess is None:
                sess = _UserSession(str(_user_data_dir(uid) / "demo_job_agent.db"))
                self._users[uid] = sess
            return sess


def run_web_server(host: str = "127.0.0.1", port: int = 7860, open_browser: bool = False) -> None:
    """Start the local web UI server."""
    for warning in settings.startup_warnings():
        log.warning("[web] config: %s", warning)
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
            if parsed.path.startswith("/static/"):
                rel_path = parsed.path.removeprefix("/static/")
                content_type = _content_type(rel_path)
                self._send_static(rel_path, content_type)
                return
            if parsed.path == "/api/auth/me":
                cookie_header = self.headers.get("Cookie", "")
                payload = _auth_me_from_cookie(cookie_header)
                cookies: list[str] = []
                if payload.get("authenticated"):
                    existing = _csrf_token_from_cookie(cookie_header)
                    if existing:
                        payload["csrf_token"] = existing
                    else:
                        csrf = _new_csrf_token()
                        payload["csrf_token"] = csrf
                        cookies = [_csrf_cookie(csrf)]
                self._send_json(payload, cookies=cookies)
                return
            user = self._current_user()
            if parsed.path.startswith("/api/") and user is None:
                self._send_json({"ok": False, "error": "Not authenticated"}, status=HTTPStatus.UNAUTHORIZED)
                return
            if parsed.path == "/api/config":
                self._send_json(_config_payload())
                return
            if parsed.path == "/api/state":
                self._send_json(_state_payload(state, user))
                return
            if parsed.path == "/api/applications":
                params = parse_qs(parsed.query)
                sess = state.session(user)
                data_root = _user_data_dir(user["id"]) if user else None
                db_path = params.get("db_path", [sess.last_db_path])[0]
                try:
                    self._send_json({"applications": _load_applications(db_path, data_root)})
                except Exception as exc:
                    self._send_json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                return
            if parsed.path == "/api/pipeline-progress":
                params = parse_qs(parsed.query)
                self._send_json(_pipeline_progress(params.get("id", [""])[0], user))
                return
            self._send_error(HTTPStatus.NOT_FOUND, "Not found")

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/auth/register":
                try:
                    response = _register_from_payload(self._read_json(), self.client_address[0])
                    self._send_authenticated(response)
                except Exception as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            if parsed.path == "/api/auth/login":
                try:
                    response = _login_from_payload(self._read_json(), self.client_address[0])
                    self._send_authenticated(response)
                except Exception as exc:
                    status = HTTPStatus.TOO_MANY_REQUESTS if "Zu viele" in str(exc) else HTTPStatus.UNAUTHORIZED
                    self._send_json({"ok": False, "error": str(exc)}, status=status)
                return
            if parsed.path == "/api/auth/logout":
                _logout_from_cookie(self.headers.get("Cookie", ""))
                self._send_json(
                    {"ok": True},
                    cookies=[_clear_session_cookie(), _clear_csrf_cookie()],
                )
                return
            user = self._current_user()
            if user is None:
                self._send_json({"ok": False, "error": "Not authenticated"}, status=HTTPStatus.UNAUTHORIZED)
                return
            if not self._csrf_ok():
                self._send_json(
                    {"ok": False, "error": "CSRF-Prüfung fehlgeschlagen."},
                    status=HTTPStatus.FORBIDDEN,
                )
                return
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
                    response = _build_profile_from_payload(payload, state, user)
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
                self._send_json(_use_demo_profile(state, user))
                return
            if parsed.path == "/api/update-status":
                try:
                    payload = self._read_json()
                    response = _update_status_from_payload(payload, state, user)
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
                    response = _send_application_email_from_payload(payload, state, user)
                except Exception as exc:
                    log.exception("[web] email submission failed")
                    self._send_json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                self._send_json(response)
                return
            if parsed.path == "/api/sync-email-status":
                try:
                    payload = self._read_json()
                    response = _sync_email_status_from_payload(payload, state, user)
                except Exception as exc:
                    log.exception("[web] email sync failed")
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
                    response = _start_pipeline_async(payload, state, user)
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
                response = _run_pipeline_from_payload(payload, state, user=user)
            except Exception as exc:
                log.exception("[web] pipeline request failed")
                state.session(user).last_error = str(exc)
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

        def _send_json(
            self,
            payload: dict[str, Any],
            status: HTTPStatus = HTTPStatus.OK,
            headers: dict[str, str] | None = None,
            cookies: list[str] | None = None,
        ) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            for cookie in cookies or []:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(body)

        def _send_error(self, status: HTTPStatus, message: str) -> None:
            self._send_json({"ok": False, "error": message}, status=status)

        def _send_authenticated(self, response: dict[str, Any]) -> None:
            """Finish a successful login/registration: set session + CSRF cookies."""
            token = str(response.pop("session_token"))
            csrf = _new_csrf_token()
            response["csrf_token"] = csrf
            self._send_json(response, cookies=[_session_cookie(token), _csrf_cookie(csrf)])

        def _current_user(self) -> AuthUser | None:
            token = _session_token_from_cookie(self.headers.get("Cookie", ""))
            store = _auth_store()
            try:
                return store.user_for_session(token)
            finally:
                store.close()

        def _csrf_ok(self) -> bool:
            """Double-submit CSRF check for state-changing requests.

            The client echoes the non-HttpOnly ``job_agent_csrf`` cookie in an
            ``X-CSRF-Token`` header. A cross-site attacker cannot read the
            cookie, so it cannot forge the header. SameSite=Lax is the first
            line of defence; this is defence in depth.
            """
            return _csrf_token_valid(
                self.headers.get("Cookie", ""), self.headers.get("X-CSRF-Token", "")
            )

    return JobAgentHandler


def _csrf_token_valid(cookie_header: str, header_token: str | None) -> bool:
    """True iff the CSRF cookie and the echoed header token match (constant time)."""
    cookie_token = _csrf_token_from_cookie(cookie_header)
    if not cookie_token or not header_token:
        return False
    return hmac.compare_digest(cookie_token, header_token)


def _auth_store() -> AuthStore:
    """Open an AuthStore against the configured auth DB.

    Centralised so the path (and any future pooling) lives in one place;
    reads the module global at call time so tests can monkeypatch it.
    """
    return AuthStore(AUTH_DB_PATH)


def _rate_limit(key: str, max_attempts: int) -> None:
    """Sliding-window throttle; raises a German ValueError when exceeded."""
    now = time.monotonic()
    with _AUTH_RATE_LOCK:
        recent = [t for t in _AUTH_ATTEMPTS.get(key, []) if now - t < _AUTH_RATE_WINDOW]
        if len(recent) >= max_attempts:
            _AUTH_ATTEMPTS[key] = recent
            raise ValueError("Zu viele Versuche. Bitte kurz warten und erneut versuchen.")
        recent.append(now)
        _AUTH_ATTEMPTS[key] = recent


def _register_from_payload(payload: dict[str, Any], client_ip: str = "local") -> dict[str, Any]:
    email = str(payload.get("email") or "")
    password = str(payload.get("password") or "")
    _rate_limit(f"register:{client_ip}", _REGISTER_MAX_ATTEMPTS)
    store = _auth_store()
    try:
        user = store.create_user(email, password)
        token = store.create_session(user["id"])
        return {"ok": True, "user": _auth_user_payload(user), "session_token": token}
    finally:
        store.close()


def _login_from_payload(payload: dict[str, Any], client_ip: str = "local") -> dict[str, Any]:
    email = str(payload.get("email") or "")
    password = str(payload.get("password") or "")
    _rate_limit(f"login:{client_ip}:{email.strip().lower()}", _LOGIN_MAX_ATTEMPTS)
    store = _auth_store()
    try:
        user = store.authenticate(email, password)
        if user is None:
            raise ValueError("E-Mail oder Passwort ist falsch.")
        token = store.create_session(user["id"])
        return {"ok": True, "user": _auth_user_payload(user), "session_token": token}
    finally:
        store.close()


def _logout_from_cookie(cookie_header: str) -> None:
    token = _session_token_from_cookie(cookie_header)
    store = _auth_store()
    try:
        store.delete_session(token)
    finally:
        store.close()


def _auth_me_from_cookie(cookie_header: str) -> dict[str, Any]:
    token = _session_token_from_cookie(cookie_header)
    store = _auth_store()
    try:
        user = store.user_for_session(token)
        if user is None:
            return {"ok": True, "authenticated": False, "user": None}
        return {"ok": True, "authenticated": True, "user": _auth_user_payload(user)}
    finally:
        store.close()


def _auth_user_payload(user: AuthUser) -> dict[str, Any]:
    return {"id": user["id"], "email": user["email"], "created_at": user["created_at"]}


def _cookie_value_from_header(cookie_header: str, name: str) -> str | None:
    for part in cookie_header.split(";"):
        key, _, value = part.strip().partition("=")
        if key == name and value:
            return value
    return None


def _session_token_from_cookie(cookie_header: str) -> str | None:
    return _cookie_value_from_header(cookie_header, AUTH_COOKIE)


def _csrf_token_from_cookie(cookie_header: str) -> str | None:
    return _cookie_value_from_header(cookie_header, CSRF_COOKIE)


def _new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def _cookie_attrs(http_only: bool) -> str:
    attrs = f"Path=/; Max-Age={AUTH_COOKIE_MAX_AGE}; SameSite=Lax"
    if http_only:
        attrs = "HttpOnly; " + attrs
    if settings.web_secure_cookies:
        attrs += "; Secure"
    return attrs


def _session_cookie(token: str) -> str:
    return f"{AUTH_COOKIE}={token}; {_cookie_attrs(http_only=True)}"


def _csrf_cookie(token: str) -> str:
    # Readable by JS so the client can echo it back in the X-CSRF-Token header.
    return f"{CSRF_COOKIE}={token}; {_cookie_attrs(http_only=False)}"


def _clear_session_cookie() -> str:
    return f"{AUTH_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"


def _clear_csrf_cookie() -> str:
    return f"{CSRF_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax"


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


def _remember_profile(
    state: WebState | None, user: AuthUser | None, profile: UserProfile, source: str
) -> None:
    if state is None:
        return
    sess = state.session(user)
    with state.lock:
        sess.current_profile = profile
        sess.current_profile_source = source


def _build_profile_from_payload(
    payload: dict[str, Any], state: WebState | None = None, user: AuthUser | None = None
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
            _remember_profile(state, user, profile, "cv")
            return {"ok": True, "source": "cv", "profile": _profile_dump(profile)}
        except Exception as exc:
            log.warning("[web] profiler failed, showing demo preview: %s", exc)
            profile = demo_profile()
            _remember_profile(state, user, profile, "demo")
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
    _remember_profile(state, user, profile, "demo")
    return {"ok": True, "source": "demo", "profile": _profile_dump(profile)}


def _use_demo_profile(state: WebState, user: AuthUser | None = None) -> dict[str, Any]:
    profile = demo_profile()
    _remember_profile(state, user, profile, "demo")
    return {"ok": True, "source": "demo", "profile": _profile_dump(profile)}


def _run_pipeline_from_payload(
    payload: dict[str, Any],
    state: WebState,
    progress: ProgressFn | None = None,
    user: AuthUser | None = None,
) -> dict[str, Any]:
    sess = state.session(user)
    data_root = _user_data_dir(user["id"]) if user else None
    demo = bool(payload.get("demo", True))
    query = str(payload.get("query") or "Werkstudent KI")
    limit = _bounded_int(payload.get("limit"), default=5, minimum=1, maximum=25)
    threshold = _bounded_float(payload.get("threshold"), default=0.5, minimum=0.0, maximum=1.0)
    draft_all = bool(payload.get("draft_all", False))
    use_llm = bool(payload.get("llm_agents", False))
    use_chroma = bool(payload.get("chroma", False))
    reset_db = bool(payload.get("reset_db", False))
    db_path = _resolve_db_path(
        str(payload.get("db_path") or (DEFAULT_DEMO_DB if demo else settings.sqlite_path)),
        data_root,
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
            sess.current_profile = profile
            sess.current_profile_source = profile_source
    elif cv_text:
        from job_agent.agents.profiler import run_profiler

        if progress is not None:
            progress("Profil aus CV erstellen", 5)
        log.info("[web] building profile from pasted CV (%d chars)", len(cv_text))
        profile = run_profiler(cv_text)
        used_cv = True
        profile_source = "cv"
        with state.lock:
            sess.current_profile = profile
            sess.current_profile_source = profile_source
    else:
        with state.lock:
            current_profile = sess.current_profile
            current_profile_source = sess.current_profile_source
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
        sess.last_result = result
        sess.last_db_path = str(db_path)
        sess.last_error = None

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


def _start_pipeline_async(
    payload: dict[str, Any], state: WebState, user: AuthUser | None = None
) -> dict[str, Any]:
    """Run the pipeline in a background thread, tracking progress by job id."""
    job_id = uuid.uuid4().hex
    owner = int(user["id"]) if user else None
    with _PROGRESS_LOCK:
        if len(_PROGRESS) > 40:
            for old in list(_PROGRESS)[:20]:
                _PROGRESS.pop(old, None)
        _PROGRESS[job_id] = {
            "owner": owner,
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
            result = _run_pipeline_from_payload(payload, state, progress=progress, user=user)
            with _PROGRESS_LOCK:
                _PROGRESS[job_id].update(result=result, done=True, percent=100, stage="Fertig")
        except Exception as exc:
            log.exception("[web] async pipeline failed")
            with _PROGRESS_LOCK:
                _PROGRESS[job_id].update(error=str(exc), done=True, stage="Fehler")

    threading.Thread(target=worker, daemon=True).start()
    return {"ok": True, "job_id": job_id}


def _pipeline_progress(job_id: str, user: AuthUser | None = None) -> dict[str, Any]:
    owner = int(user["id"]) if user else None
    with _PROGRESS_LOCK:
        entry = _PROGRESS.get(job_id)
        if entry is None or entry.get("owner") != owner:
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


def _state_payload(state: WebState, user: AuthUser | None = None) -> dict[str, Any]:
    sess = state.session(user)
    data_root = _user_data_dir(user["id"]) if user else None
    with state.lock:
        result = sess.last_result
        db_path = sess.last_db_path
        error = sess.last_error
        current_profile = sess.current_profile
        current_profile_source = sess.current_profile_source
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
        statuses = _safe_statuses(db_path, data_root)
        payload["summary"] = _summary_payload(result)
        payload["jobs"] = [_job_payload(job, result.matches, statuses) for job in result.jobs]
        payload["applications"] = _load_applications(db_path, data_root)
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
        "email_sync_dry_run": settings.email_sync_dry_run,
        "email_sync_ready": bool(
            settings.email_imap_host and settings.email_imap_user and settings.email_imap_password
        ),
        "llm_agents_default": settings.enable_llm_agents,
        "chroma_default": settings.enable_chroma,
        "max_cv_upload_mb": MAX_CV_UPLOAD_BYTES // (1024 * 1024),
        "default_demo_db": str(_resolve_db_path(DEFAULT_DEMO_DB)),
        "default_live_db": str(_resolve_db_path(settings.sqlite_path)),
    }


def _load_applications(db_path: str, data_root: Path | None = None) -> list[dict[str, Any]]:
    store = Store(_resolve_db_path(db_path, data_root))
    try:
        statuses = store.all_status()
        return [
            _application_payload(app, statuses)
            for status in statuses
            if (app := store.get_application(status.job_id))
        ]
    finally:
        store.close()


def _update_status_from_payload(
    payload: dict[str, Any], state: WebState, user: AuthUser | None = None
) -> dict[str, Any]:
    sess = state.session(user)
    data_root = _user_data_dir(user["id"]) if user else None
    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("job_id is required")

    status = str(payload.get("status") or "draft").strip()
    if status not in STATUS_STAGES:
        allowed = ", ".join(sorted(STATUS_STAGES))
        raise ValueError(f"Unknown status '{status}'. Allowed: {allowed}.")

    notes = str(payload.get("notes") or "")[:1000]
    db_path = _resolve_db_path(str(payload.get("db_path") or sess.last_db_path), data_root)
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
        sess.last_db_path = str(db_path)

    return {
        "ok": True,
        "status": record.model_dump(mode="json"),
        "applications": applications,
    }


def _send_application_email_from_payload(
    payload: dict[str, Any], state: WebState, user: AuthUser | None = None
) -> dict[str, Any]:
    from job_agent.tools.email_delivery import send_application_email

    sess = state.session(user)
    data_root = _user_data_dir(user["id"]) if user else None
    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("job_id is required")

    recipient = str(payload.get("recipient") or "").strip() or None
    db_path = _resolve_db_path(str(payload.get("db_path") or sess.last_db_path), data_root)
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
        sess.last_db_path = str(db_path)

    return {
        "ok": True,
        "email": email_result,
        "status": record.model_dump(mode="json"),
        "applications": applications,
    }


def _sync_email_status_from_payload(
    payload: dict[str, Any], state: WebState, user: AuthUser | None = None
) -> dict[str, Any]:
    from job_agent.tools.email_sync import sync_email_statuses

    sess = state.session(user)
    data_root = _user_data_dir(user["id"]) if user else None
    db_path = _resolve_db_path(str(payload.get("db_path") or sess.last_db_path), data_root)
    limit = _bounded_int(payload.get("limit"), default=settings.email_sync_limit, minimum=1, maximum=200)
    store = Store(db_path)
    try:
        sync_result = sync_email_statuses(store, limit=limit)
        statuses = store.all_status()
        applications = [
            _application_payload(app, statuses)
            for item in statuses
            if (app := store.get_application(item.job_id))
        ]
    finally:
        store.close()

    with state.lock:
        sess.last_db_path = str(db_path)

    return {
        "ok": True,
        "sync": sync_result,
        "applications": applications,
    }


def _append_note(existing: str, event: str) -> str:
    merged = f"{existing}\n{event}".strip() if existing else event
    return merged[-1000:]


def _safe_statuses(db_path: str, data_root: Path | None = None) -> list[ApplicationStatus]:
    try:
        store = Store(_resolve_db_path(db_path, data_root))
        try:
            return store.all_status()
        finally:
            store.close()
    except Exception:
        return []


def _resolve_db_path(db_path: str, data_root: Path | None = None) -> Path:
    """Resolve a SQLite path, confined to an allowed root.

    With ``data_root`` (a per-user directory) the path is forced inside that
    directory: anything pointing elsewhere is re-based by filename, so one
    account can never read or write another account's database. Without it the
    legacy behaviour applies — confined to the shared project ``data`` dir, and
    out-of-tree paths are rejected outright.
    """
    root = (data_root or DATA_DIR).resolve(strict=False)
    raw_path = Path(db_path).expanduser()
    candidate = raw_path if raw_path.is_absolute() else REPO_ROOT / raw_path
    resolved = candidate.resolve(strict=False)

    if resolved != root and root not in resolved.parents:
        if data_root is not None:
            # Per-user isolation: keep only the filename, place it under the
            # user's own directory (strips any traversal or cross-user path).
            resolved = (root / raw_path.name).resolve(strict=False)
        else:
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
        "source_label": _source_label(job.source),
        "url": str(job.url),
        "remote": job.remote,
        "employment_type": job.employment_type,
        "salary_range": job.salary_range,
        "requirements": job.requirements,
        "nice_to_have": job.nice_to_have,
        "description": job.description,
        "score": match.score if match else None,
        "score_explanation": _score_explanation(job, match),
        "score_components": [
            component.model_dump(mode="json")
            for component in (match.score_components if match else [])
        ],
        "risk_level": match.risk_level if match else "low",
        "risk_flags": match.risk_flags if match else [],
        "recommendation": match.recommendation if match else "maybe",
        "score_summary": match.score_summary if match else "",
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
    if match.score_summary:
        return match.score_summary
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


def _source_label(source: str) -> str:
    return {
        "adzuna": "Adzuna",
        "ba-jobsuche": "Arbeitsagentur",
        "stepstone": "StepStone",
        "linkedin": "LinkedIn",
        "manual": "Manuell",
    }.get(source, source)


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
