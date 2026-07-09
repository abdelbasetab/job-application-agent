"""Small stdlib web UI for the Job Application Agent."""

from __future__ import annotations

import base64
import binascii
import hmac
import html
import json
import os
import secrets
import shutil
import tempfile
import threading
import time
import uuid
import webbrowser
from collections.abc import Callable
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from job_agent.agents.demo_scout import run_demo_scout
from job_agent.demo_profile import demo_profile
from job_agent.memory.auth_store import AuthStore, AuthUser
from job_agent.memory.credential_store import CredentialStore
from job_agent.memory.store import Store
from job_agent.pipeline import PipelineResult, run_pipeline
from job_agent.schemas import (
    ApplicationStatus,
    GeneratedApplication,
    JobPosting,
    LivenessResult,
    MatchResult,
    UserProfile,
)
from job_agent.tools.email_account import (
    EmailAccount,
    account_from_mapping,
    account_from_settings,
    email_identity_payload,
)
from job_agent.tools.email_oauth import (
    build_authorization_url,
    exchange_code_for_account,
    oauth_provider,
    oauth_provider_status,
    refresh_oauth_account,
)
from job_agent.tools.recipient_extraction import best_recipient, recipient_payload
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
FRONTEND_ROUTES = {"/profil", "/suche", "/inbox", "/bewerbungen", "/followups", "/einstellungen"}

ProgressFn = Callable[[str, int], None]

_PROGRESS_LOCK = threading.Lock()
_PROGRESS: dict[str, dict[str, Any]] = {}
_AUTOPILOT_LOCK = threading.Lock()
_AUTOPILOT_SCHEDULES: dict[int, dict[str, Any]] = {}


def _user_data_dir(user_id: int) -> Path:
    """Per-user data root. Each account's pipeline data lives here, isolated."""
    root = (DATA_DIR / "users" / str(int(user_id))).resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _preferred_user_db(user_id: int) -> Path:
    root = _user_data_dir(user_id)
    candidates = [root / "job_agent.db", root / "demo_job_agent.db"]
    existing = [path for path in candidates if path.exists()]
    if existing:
        return max(existing, key=lambda path: path.stat().st_mtime)
    return root / "demo_job_agent.db"


class _UserSession:
    """In-memory working state scoped to a single authenticated user."""

    def __init__(self, default_db: str) -> None:
        self.last_result: PipelineResult | None = None
        self.last_db_path = default_db
        self.last_error: str | None = None
        self.current_profile: UserProfile | None = None
        self.current_profile_source = "demo"
        self.uploaded_cv_path: str | None = None
        self.uploaded_cv_name: str | None = None


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
                sess = _UserSession(str(_preferred_user_db(uid)))
                self._users[uid] = sess
            return sess


def _credential_store(user: AuthUser) -> CredentialStore:
    data_root = _user_data_dir(user["id"])
    return CredentialStore(data_root / "credentials.db", key_path=data_root / "credentials.key")


def _load_email_account(
    user: AuthUser | None,
    *,
    refresh_oauth: bool = False,
) -> tuple[EmailAccount, str]:
    if user is None:
        return account_from_settings(), "env"
    store = _credential_store(user)
    try:
        payload = store.load_json("email")
    finally:
        store.close()
    if payload:
        account = account_from_mapping(payload, fallback_email=user["email"])
        if refresh_oauth and _should_refresh_oauth(account):
            account = _refresh_and_store_oauth_account(user, account)
        return account, "local"
    return account_from_settings(), "env"


def _should_refresh_oauth(account: EmailAccount) -> bool:
    return (
        account.auth_method == "oauth"
        and bool(account.refresh_token)
        and (account.oauth_expired or not account.access_token)
    )


def _refresh_and_store_oauth_account(user: AuthUser, account: EmailAccount) -> EmailAccount:
    refreshed = refresh_oauth_account(account)
    store = _credential_store(user)
    try:
        store.save_json("email", refreshed.secret_dict())
    finally:
        store.close()
    return refreshed


def _email_identity_for(
    state: WebState,
    user: AuthUser | None,
    account: EmailAccount | None = None,
    account_source: str | None = None,
) -> dict[str, Any]:
    sess = state.session(user)
    with state.lock:
        profile = sess.current_profile
    resolved, source = (account, account_source or "local") if account else _load_email_account(user)
    return email_identity_payload(
        profile,
        user_email=user["email"] if user else None,
        account=resolved,
        account_source=source,
    )


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
            if parsed.path in ("/", "/index.html") or parsed.path in FRONTEND_ROUTES:
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
                self._send_json(_config_payload(state, user))
                return
            if parsed.path == "/api/email-audit":
                params = parse_qs(parsed.query)
                try:
                    self._send_json(_email_audit_payload(params, state, user))
                except Exception as exc:
                    self._send_json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                return
            if parsed.path == "/api/oauth/email/callback":
                params = parse_qs(parsed.query)
                try:
                    html = _complete_email_oauth_from_params(params, state, user)
                    self._send_html(html)
                except Exception as exc:
                    log.exception("[web] email oauth callback failed")
                    self._send_html(_oauth_result_html(False, str(exc)), status=HTTPStatus.BAD_REQUEST)
                return
            if parsed.path == "/api/email-autopilot-schedule":
                self._send_json(_email_autopilot_schedule_payload(user))
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
            if parsed.path == "/api/follow-ups":
                params = parse_qs(parsed.query)
                try:
                    self._send_json(_follow_ups_payload(params, state, user))
                except Exception as exc:
                    self._send_json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                return
            if parsed.path == "/api/inbox":
                try:
                    self._send_json(_inbox_payload(state, user))
                except Exception as exc:
                    self._send_json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                return
            if parsed.path == "/api/patterns":
                params = parse_qs(parsed.query)
                try:
                    self._send_json(_patterns_payload(params, state, user))
                except Exception as exc:
                    self._send_json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                return
            if parsed.path == "/api/interview-prep":
                params = parse_qs(parsed.query)
                try:
                    self._send_json(_interview_prep_payload(params, state, user))
                except Exception as exc:
                    self._send_json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                return
            if parsed.path == "/api/download":
                params = parse_qs(parsed.query)
                try:
                    path = _download_path(
                        user, params.get("job_id", [""])[0], params.get("file", [""])[0]
                    )
                except Exception as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self._send_file(path)
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
                    response = _extract_cv_from_payload(payload, state, user)
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
            if parsed.path == "/api/email-credentials":
                try:
                    payload = self._read_json()
                    response = _save_email_credentials_from_payload(payload, state, user)
                except Exception as exc:
                    log.exception("[web] email credential save failed")
                    self._send_json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                self._send_json(response)
                return
            if parsed.path == "/api/test-email-connection":
                try:
                    payload = self._read_json()
                    response = _test_email_connection_from_payload(payload, state, user)
                except Exception as exc:
                    log.exception("[web] email connection test failed")
                    self._send_json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                self._send_json(response)
                return
            if parsed.path == "/api/oauth/email/start":
                try:
                    payload = self._read_json()
                    response = _start_email_oauth_from_payload(
                        payload,
                        state,
                        user,
                        host_header=self.headers.get("Host", ""),
                    )
                except Exception as exc:
                    log.exception("[web] email oauth start failed")
                    self._send_json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                self._send_json(response)
                return
            if parsed.path == "/api/run-email-autopilot":
                try:
                    payload = self._read_json()
                    response = _run_email_autopilot_from_payload(payload, state, user)
                except Exception as exc:
                    log.exception("[web] email autopilot failed")
                    self._send_json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                self._send_json(response)
                return
            if parsed.path == "/api/email-autopilot-schedule":
                try:
                    payload = self._read_json()
                    response = _configure_email_autopilot_schedule_from_payload(
                        payload, state, user
                    )
                except Exception as exc:
                    log.exception("[web] email autopilot schedule failed")
                    self._send_json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                self._send_json(response)
                return
            if parsed.path == "/api/check-liveness":
                try:
                    payload = self._read_json()
                    response = _check_liveness_from_payload(payload, state, user)
                except Exception as exc:
                    log.exception("[web] liveness check failed")
                    self._send_json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                self._send_json(response)
                return
            if parsed.path == "/api/export-application":
                try:
                    payload = self._read_json()
                    response = _export_application_from_payload(payload, state, user)
                except Exception as exc:
                    log.exception("[web] export failed")
                    self._send_json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                self._send_json(response)
                return
            if parsed.path == "/api/generate-draft":
                try:
                    payload = self._read_json()
                    response = _generate_draft_from_payload(payload, state, user)
                except Exception as exc:
                    log.exception("[web] draft generation failed")
                    self._send_json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                self._send_json(response)
                return
            if parsed.path == "/api/review-cv":
                try:
                    payload = self._read_json()
                    response = _review_cv_from_payload(payload, state, user)
                except Exception as exc:
                    log.exception("[web] CV review failed")
                    self._send_json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                self._send_json(response)
                return
            if parsed.path == "/api/record-follow-up":
                try:
                    payload = self._read_json()
                    response = _record_follow_up_from_payload(payload, state, user)
                except Exception as exc:
                    log.exception("[web] follow-up record failed")
                    self._send_json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                self._send_json(response)
                return
            if parsed.path == "/api/send-follow-up-email":
                try:
                    payload = self._read_json()
                    response = _send_follow_up_email_from_payload(payload, state, user)
                except Exception as exc:
                    log.exception("[web] follow-up email failed")
                    self._send_json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                self._send_json(response)
                return
            if parsed.path == "/api/inbox":
                try:
                    payload = self._read_json()
                    response = _inbox_add_from_payload(payload, state, user)
                except Exception as exc:
                    log.exception("[web] inbox add failed")
                    self._send_json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                self._send_json(response)
                return
            if parsed.path == "/api/inbox/update":
                try:
                    payload = self._read_json()
                    response = _inbox_update_from_payload(payload, state, user)
                except Exception as exc:
                    log.exception("[web] inbox update failed")
                    self._send_json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                self._send_json(response)
                return
            if parsed.path == "/api/inbox/evaluate":
                try:
                    payload = self._read_json()
                    response = _inbox_evaluate_from_payload(payload, state, user)
                except Exception as exc:
                    log.exception("[web] inbox evaluate failed")
                    self._send_json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                self._send_json(response)
                return
            if parsed.path == "/api/export-report":
                try:
                    payload = self._read_json()
                    response = _export_report_from_payload(payload, state, user)
                except Exception as exc:
                    log.exception("[web] report export failed")
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

        def _send_file(self, path: Path) -> None:
            content_types = {
                ".pdf": "application/pdf",
                ".zip": "application/zip",
                ".json": "application/json; charset=utf-8",
                ".md": "text/markdown; charset=utf-8",
            }
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_types.get(path.suffix.lower(), "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
            self.send_header("X-Content-Type-Options", "nosniff")
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

        def _send_html(self, html: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
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


def _extract_cv_from_payload(
    payload: dict[str, Any],
    state: WebState | None = None,
    user: AuthUser | None = None,
) -> dict[str, Any]:
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

    saved_cv = _save_uploaded_cv(raw, filename, suffix, state, user) if state is not None else None
    log.info("[web] extracted %d chars from uploaded %s", len(text), filename)
    return {
        "ok": True,
        "filename": filename,
        "chars": len(text),
        "cv_text": text,
        "saved_cv": saved_cv.name if saved_cv else "",
    }


def _save_uploaded_cv(
    raw: bytes,
    filename: str,
    suffix: str,
    state: WebState,
    user: AuthUser | None,
) -> Path:
    data_root = _user_data_dir(user["id"]) if user else None
    upload_dir = ((data_root or DATA_DIR) / "uploads").resolve(strict=False)
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = (upload_dir / f"lebenslauf_upload{suffix}").resolve(strict=False)
    if upload_dir != target.parent:
        raise ValueError("Invalid CV upload path.")
    target.write_bytes(raw)
    sess = state.session(user)
    with state.lock:
        sess.uploaded_cv_path = str(target)
        sess.uploaded_cv_name = Path(filename).name
    return target


def _uploaded_cv_path(state: WebState, user: AuthUser | None = None) -> Path | None:
    sess = state.session(user)
    with state.lock:
        remembered = sess.uploaded_cv_path
    if remembered:
        path = Path(remembered).resolve(strict=False)
        if path.is_file() and path.suffix.lower() in ALLOWED_CV_SUFFIXES:
            return path

    data_root = _user_data_dir(user["id"]) if user else None
    upload_dir = ((data_root or DATA_DIR) / "uploads").resolve(strict=False)
    if not upload_dir.is_dir():
        return None
    candidates = [
        path
        for path in upload_dir.glob("lebenslauf_upload.*")
        if path.is_file() and path.suffix.lower() in ALLOWED_CV_SUFFIXES
    ]
    if not candidates:
        return None
    path = max(candidates, key=lambda item: item.stat().st_mtime)
    with state.lock:
        sess.uploaded_cv_path = str(path)
        sess.uploaded_cv_name = path.name
    return path


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
        liveness = store.all_liveness()
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
        "jobs": [_job_payload(job, result.matches, statuses, liveness) for job in result.jobs],
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
    statuses = _safe_statuses(db_path, data_root)
    liveness = _safe_liveness(db_path, data_root)
    applications = _load_applications(db_path, data_root)
    stored_jobs = _safe_jobs(db_path, data_root)
    if user is not None and result is None and not stored_jobs and not applications:
        preferred = _preferred_user_db(user["id"])
        if str(preferred) != str(db_path):
            preferred_db = str(preferred)
            preferred_jobs = _safe_jobs(preferred_db, data_root)
            preferred_apps = _load_applications(preferred_db, data_root)
            if preferred_jobs or preferred_apps:
                db_path = preferred_db
                statuses = _safe_statuses(db_path, data_root)
                liveness = _safe_liveness(db_path, data_root)
                applications = preferred_apps
                stored_jobs = preferred_jobs
                with state.lock:
                    sess.last_db_path = db_path
    matches = result.matches if result is not None else []
    jobs_by_id = {job.id: job for job in stored_jobs}
    if result is not None:
        for job in result.jobs:
            jobs_by_id[job.id] = job
    jobs = list(jobs_by_id.values())
    if result is not None or jobs or applications:
        payload["summary"] = _summary_from_state(jobs, matches, applications, statuses)
        payload["jobs"] = [_job_payload(job, matches, statuses, liveness) for job in jobs]
        payload["applications"] = applications
    return payload


def _config_payload(
    state: WebState | None = None,
    user: AuthUser | None = None,
) -> dict[str, Any]:
    account, account_source = _load_email_account(user)
    identity = (
        _email_identity_for(state, user, account=account, account_source=account_source)
        if state is not None
        else email_identity_payload(None, user_email=user["email"] if user else None, account=account, account_source=account_source)
    )
    return {
        "ok": True,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "embedding_model": settings.embedding_model,
        "email_dry_run": settings.email_dry_run,
        "email_demo_recipient": settings.email_demo_recipient or "",
        "email_ready": settings.email_dry_run or account.smtp_ready,
        "email_sync_dry_run": settings.email_sync_dry_run,
        "email_sync_ready": account.imap_ready,
        "email_auto_follow_up_send": settings.email_auto_follow_up_send,
        "email_autopilot_interval_minutes": settings.email_autopilot_interval_minutes,
        "email_identity": identity,
        "email_oauth_providers": oauth_provider_status(),
        "email_autopilot_schedule": _email_autopilot_schedule_payload(user),
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


def _save_email_credentials_from_payload(
    payload: dict[str, Any], state: WebState, user: AuthUser | None = None
) -> dict[str, Any]:
    if user is None:
        raise ValueError("Login required for local email credentials.")
    if str(payload.get("action") or "").strip().lower() == "clear":
        store = _credential_store(user)
        try:
            store.delete("email")
        finally:
            store.close()
        return {"ok": True, "email_identity": _email_identity_for(state, user)}

    sess = state.session(user)
    with state.lock:
        profile = sess.current_profile
    fallback_email = profile.email if profile else user["email"]
    store = _credential_store(user)
    try:
        existing = store.load_json("email") or {}
        merged = {**existing, **payload}
        for key in ("smtp_password", "imap_password"):
            if not str(payload.get(key) or "").strip() and existing.get(key):
                merged[key] = existing[key]
        account = account_from_mapping(merged, fallback_email=fallback_email)
        if not account.email_address:
            raise ValueError("E-Mail-Adresse ist erforderlich.")
        store.save_json("email", account.secret_dict())
    finally:
        store.close()
    return {
        "ok": True,
        "email_identity": _email_identity_for(
            state, user, account=account, account_source="local"
        ),
    }


def _test_email_connection_from_payload(
    payload: dict[str, Any], state: WebState, user: AuthUser | None = None
) -> dict[str, Any]:
    """Run a no-send SMTP/IMAP connection test for the active account."""
    from job_agent.tools.email_connection import test_email_connections

    if user is None:
        raise ValueError("Login required for email connection tests.")
    kind = str(payload.get("kind") or "both").strip().lower()
    if kind not in {"smtp", "imap", "both"}:
        raise ValueError("Unknown email connection test. Use 'smtp', 'imap', or 'both'.")
    account, account_source = _load_email_account(user, refresh_oauth=True)
    timeout = _bounded_float(payload.get("timeout"), default=15.0, minimum=3.0, maximum=60.0)
    result = test_email_connections(account, kind=kind, timeout=timeout)  # type: ignore[arg-type]
    result["account_source"] = account_source
    result["email_identity"] = _email_identity_for(
        state,
        user,
        account=account,
        account_source=account_source,
    )
    return result


def _email_audit_payload(
    params: dict[str, list[str]], state: WebState, user: AuthUser | None = None
) -> dict[str, Any]:
    sess = state.session(user)
    data_root = _user_data_dir(user["id"]) if user else None
    db_path = _resolve_db_path(params.get("db_path", [sess.last_db_path])[0], data_root)
    limit = _bounded_int(params.get("limit", ["30"])[0], default=30, minimum=1, maximum=200)
    store = Store(db_path)
    try:
        events = store.email_audit(limit=limit)
    finally:
        store.close()
    return {"ok": True, "events": events}


def _start_email_oauth_from_payload(
    payload: dict[str, Any],
    state: WebState,
    user: AuthUser | None,
    *,
    host_header: str,
) -> dict[str, Any]:
    if user is None:
        raise ValueError("Login required for OAuth.")
    provider = oauth_provider(str(payload.get("provider") or ""))
    redirect_uri = _oauth_redirect_uri(host_header)
    nonce = secrets.token_urlsafe(32)
    sess = state.session(user)
    with state.lock:
        profile = sess.current_profile
    login_hint = (
        str(payload.get("email") or "").strip().lower()
        or (profile.email.strip().lower() if profile else "")
        or user["email"]
    )
    store = _credential_store(user)
    try:
        store.save_json(
            "email_oauth_state",
            {
                "state": nonce,
                "provider": provider.key,
                "redirect_uri": redirect_uri,
                "email": login_hint,
                "created_at": datetime.now().isoformat(),
            },
        )
    finally:
        store.close()
    return {
        "ok": True,
        "provider": provider.key,
        "authorization_url": build_authorization_url(
            provider,
            redirect_uri=redirect_uri,
            state=nonce,
            login_hint=login_hint,
        ),
    }


def _complete_email_oauth_from_params(
    params: dict[str, list[str]],
    state: WebState,
    user: AuthUser | None,
) -> str:
    if user is None:
        raise ValueError("Login required for OAuth callback.")
    code = str(params.get("code", [""])[0]).strip()
    returned_state = str(params.get("state", [""])[0]).strip()
    if not code or not returned_state:
        raise ValueError("OAuth callback is missing code or state.")
    store = _credential_store(user)
    try:
        saved = store.load_json("email_oauth_state") or {}
        if not hmac.compare_digest(str(saved.get("state") or ""), returned_state):
            raise ValueError("OAuth state mismatch.")
        created_at = datetime.fromisoformat(str(saved.get("created_at")))
        if created_at + timedelta(minutes=15) < datetime.now(created_at.tzinfo):
            raise ValueError("OAuth state expired. Please start again.")
        provider = oauth_provider(str(saved.get("provider") or ""))
        account = exchange_code_for_account(
            provider,
            code=code,
            redirect_uri=str(saved.get("redirect_uri") or ""),
            email_address=str(saved.get("email") or user["email"]),
        )
        store.save_json("email", account.secret_dict())
        store.delete("email_oauth_state")
    finally:
        store.close()
    return _oauth_result_html(True, f"{provider.label} wurde verbunden.")


def _oauth_redirect_uri(host_header: str) -> str:
    base = settings.email_oauth_redirect_base
    if not base:
        host = host_header.strip() or f"{settings.web_host}:{settings.web_port}"
        base = f"http://{host}"
    return base.rstrip("/") + "/api/oauth/email/callback"


def _oauth_result_html(ok: bool, message: str) -> str:
    status = "ok" if ok else "error"
    safe = html.escape(message)
    return f"""<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8" />
    <meta http-equiv="refresh" content="1; url=/#/profil?oauth={status}" />
    <title>E-Mail OAuth</title>
    <style>
      body {{ font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; padding: 32px; }}
      div {{ max-width: 560px; margin: 12vh auto; }}
    </style>
  </head>
  <body><div><h1>{'Verbunden' if ok else 'Nicht verbunden'}</h1><p>{safe}</p></div></body>
</html>"""


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
    account, account_source = _load_email_account(user, refresh_oauth=True)
    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("job_id is required")

    recipient = str(payload.get("recipient") or "").strip() or None
    attach_cv = bool(payload.get("attach_cv", False))
    db_path = _resolve_db_path(str(payload.get("db_path") or sess.last_db_path), data_root)

    attachments: list[Path] = []
    if attach_cv:
        cv_path = _application_cv_path(state, user, data_root, job_id)
        attachments = [cv_path]

    store = Store(db_path)
    try:
        job = store.get_job(job_id)
        application = store.get_application(job_id)
        if job is None:
            raise ValueError(f"Job '{job_id}' not found in store.")
        if application is None:
            raise ValueError(f"No drafted application exists for job '{job_id}'.")

        # Prefer the address from the posting; the fixed config recipient is only
        # a last-resort fallback (e.g. for offline demo jobs without an email).
        recipient = recipient or _extract_contact_email(job) or None
        email_result = send_application_email(
            job,
            application,
            recipient=recipient,
            attachments=attachments,
            account=account,
        )
        store.record_email_audit(
            "application_email",
            _safe_email_audit_payload(email_result, account_source),
            job_id=job_id,
        )
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
        if email_result.get("attachments"):
            event += f" Anhang: {', '.join(email_result['attachments'])}."
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
    account, account_source = _load_email_account(user, refresh_oauth=True)
    db_path = _resolve_db_path(str(payload.get("db_path") or sess.last_db_path), data_root)
    limit = _bounded_int(payload.get("limit"), default=settings.email_sync_limit, minimum=1, maximum=200)
    store = Store(db_path)
    try:
        sync_result = sync_email_statuses(store, limit=limit, account=account)
        store.record_email_audit(
            "inbox_sync",
            _safe_sync_audit_payload(sync_result, account_source),
        )
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


def _review_cv_from_payload(
    payload: dict[str, Any], state: WebState, user: AuthUser | None = None
) -> dict[str, Any]:
    """Explainable CV quality review (deterministic rubric, optional LLM extra)."""
    from job_agent.agents.cv_reviewer import run_cv_reviewer

    cv_text = str(payload.get("cv_text") or "").strip()
    if not cv_text:
        raise ValueError("cv_text is required — bitte zuerst einen Lebenslauf einfügen.")
    use_llm = bool(payload.get("llm", False))

    sess = state.session(user)
    with state.lock:
        profile = sess.current_profile
        source = sess.current_profile_source
    # Only pass the structured profile when it actually came from this CV —
    # the demo profile would skew the skills/languages dimensions.
    context_profile = profile if (profile is not None and source == "cv") else None

    assessment = run_cv_reviewer(cv_text, profile=context_profile, use_llm=use_llm)
    return {"ok": True, "assessment": assessment.model_dump(mode="json")}


def _follow_ups_payload(
    params: dict[str, list[str]], state: WebState, user: AuthUser | None = None
) -> dict[str, Any]:
    """All submitted applications currently due for a follow-up nudge."""
    from job_agent.agents.tracker import FOLLOW_UP_AFTER_DAYS, due_follow_ups

    sess = state.session(user)
    data_root = _user_data_dir(user["id"]) if user else None
    days = _bounded_int(
        params.get("days", [str(FOLLOW_UP_AFTER_DAYS)])[0],
        default=FOLLOW_UP_AFTER_DAYS,
        minimum=1,
        maximum=60,
    )
    db_path = _resolve_db_path(params.get("db_path", [sess.last_db_path])[0], data_root)
    with state.lock:
        profile = sess.current_profile
    candidate = profile.name if profile else demo_profile().name

    store = Store(db_path)
    try:
        items = due_follow_ups(store, days=days, candidate_name=candidate)
        jobs = {job.id: job for job in store.all_jobs()}
    finally:
        store.close()
    enriched: list[dict[str, Any]] = []
    for item in items:
        row = item.model_dump(mode="json")
        job = jobs.get(item.job_id)
        if job is not None:
            row.update(recipient_payload(job))
        else:
            row.update({"contact_email": "", "recipient_suggestions": [], "recipient_confidence": 0.0})
        enriched.append(row)
    return {
        "ok": True,
        "days": days,
        "follow_ups": enriched,
    }


def _record_follow_up_from_payload(
    payload: dict[str, Any], state: WebState, user: AuthUser | None = None
) -> dict[str, Any]:
    """Mark a follow-up as done — resets the cadence clock for that job."""
    from job_agent.agents.tracker import record_follow_up

    sess = state.session(user)
    data_root = _user_data_dir(user["id"]) if user else None
    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("job_id is required")
    db_path = _resolve_db_path(str(payload.get("db_path") or sess.last_db_path), data_root)

    store = Store(db_path)
    try:
        record = record_follow_up(store, job_id)
        statuses = store.all_status()
        applications = [
            _application_payload(app, statuses)
            for item in statuses
            if (app := store.get_application(item.job_id))
        ]
    finally:
        store.close()
    return {
        "ok": True,
        "status": record.model_dump(mode="json"),
        "applications": applications,
    }


def _send_follow_up_email_from_payload(
    payload: dict[str, Any], state: WebState, user: AuthUser | None = None
) -> dict[str, Any]:
    """Send (or dry-run) the follow-up email and log it on the application."""
    from job_agent.agents.tracker import follow_up_email_draft, record_follow_up
    from job_agent.tools.email_delivery import send_follow_up_email

    sess = state.session(user)
    data_root = _user_data_dir(user["id"]) if user else None
    account, account_source = _load_email_account(user, refresh_oauth=True)
    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("job_id is required")
    recipient = str(payload.get("recipient") or "").strip() or None
    body_md = str(payload.get("body_md") or "").strip()
    db_path = _resolve_db_path(str(payload.get("db_path") or sess.last_db_path), data_root)

    store = Store(db_path)
    try:
        job = store.get_job(job_id)
        if job is None:
            raise ValueError(f"Job '{job_id}' not found in store.")
        status = store.get_status(job_id)
        if status is None:
            raise ValueError(f"No tracked application for job '{job_id}'.")
        if not body_md:
            with state.lock:
                profile = sess.current_profile
            candidate = profile.name if profile else demo_profile().name
            body_md = follow_up_email_draft(
                job.title, job.company, status.submitted_at, candidate
            )
        recipient = recipient or _extract_contact_email(job) or None
        email_result = send_follow_up_email(
            job,
            body_md,
            recipient=recipient,
            account=account,
        )
        store.record_email_audit(
            "follow_up_email",
            _safe_email_audit_payload(email_result, account_source),
            job_id=job_id,
        )
        event = (
            f"Follow-up-E-Mail gesendet an {email_result['recipient']}."
            if email_result["sent"]
            else f"Follow-up-E-Mail (Dry-run) vorbereitet an {email_result['recipient']}."
        )
        record = record_follow_up(store, job_id, note=event)
        statuses = store.all_status()
        applications = [
            _application_payload(app, statuses)
            for item in statuses
            if (app := store.get_application(item.job_id))
        ]
    finally:
        store.close()
    return {
        "ok": True,
        "email": email_result,
        "status": record.model_dump(mode="json"),
        "applications": applications,
    }


def _run_email_autopilot_from_payload(
    payload: dict[str, Any], state: WebState, user: AuthUser | None = None
) -> dict[str, Any]:
    """One safe autonomous mail pass: inbox sync plus due follow-up handling."""
    from job_agent.agents.tracker import FOLLOW_UP_AFTER_DAYS, due_follow_ups, record_follow_up
    from job_agent.tools.email_delivery import send_follow_up_email
    from job_agent.tools.email_sync import sync_email_statuses

    sess = state.session(user)
    data_root = _user_data_dir(user["id"]) if user else None
    account, account_source = _load_email_account(user, refresh_oauth=True)
    db_path = _resolve_db_path(str(payload.get("db_path") or sess.last_db_path), data_root)
    limit = _bounded_int(payload.get("limit"), default=settings.email_sync_limit, minimum=1, maximum=200)
    days = _bounded_int(
        payload.get("days"),
        default=FOLLOW_UP_AFTER_DAYS,
        minimum=1,
        maximum=60,
    )
    with state.lock:
        profile = sess.current_profile
    candidate = profile.name if profile else demo_profile().name

    actions: list[dict[str, Any]] = []
    store = Store(db_path)
    try:
        if account.imap_ready:
            sync_result = sync_email_statuses(store, limit=limit, account=account)
        else:
            sync_result = {
                "ok": False,
                "dry_run": settings.email_sync_dry_run,
                "updates": [],
                "error": "IMAP nicht konfiguriert.",
            }
        for item in due_follow_ups(store, days=days, candidate_name=candidate):
            job = store.get_job(item.job_id)
            if job is None:
                continue
            recipient = _extract_contact_email(job)
            action: dict[str, Any] = {
                "job_id": item.job_id,
                "title": item.title,
                "company": item.company,
                "recipient": recipient,
                "mode": "prepared",
                "sent": False,
                "dry_run": True,
            }
            if not recipient:
                action["mode"] = "skipped"
                action["reason"] = "Keine Bewerbungsadresse erkannt."
                actions.append(action)
                continue
            if settings.email_auto_follow_up_send:
                try:
                    email_result = send_follow_up_email(
                        job,
                        item.suggested_email_md,
                        recipient=recipient,
                        account=account,
                    )
                    action.update(_safe_email_audit_payload(email_result, account_source))
                    action["mode"] = "sent" if email_result.get("sent") else "dry_run"
                    if email_result.get("sent"):
                        record_follow_up(
                            store,
                            item.job_id,
                            note=f"Autopilot Follow-up gesendet an {email_result['recipient']}.",
                        )
                except Exception as exc:
                    action["mode"] = "error"
                    action["error"] = str(exc)
            actions.append(action)
        store.record_email_audit(
            "email_autopilot",
            {
                "account_source": account_source,
                "sync_seen": int(sync_result.get("seen") or 0),
                "sync_classified": int(sync_result.get("classified") or 0),
                "sync_matched": int(sync_result.get("matched") or 0),
                "sync_updates": len(sync_result.get("updates", [])),
                "sync_unmatched": list(sync_result.get("unmatched") or [])[:3],
                "actions": [
                    {
                        "job_id": action.get("job_id"),
                        "mode": action.get("mode"),
                        "recipient": action.get("recipient"),
                    }
                    for action in actions
                ],
                "auto_send_enabled": settings.email_auto_follow_up_send,
            },
        )
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
        "actions": actions,
        "applications": applications,
        "auto_send_enabled": settings.email_auto_follow_up_send,
    }


def _configure_email_autopilot_schedule_from_payload(
    payload: dict[str, Any],
    state: WebState,
    user: AuthUser | None = None,
) -> dict[str, Any]:
    action = str(payload.get("action") or "start").strip().lower()
    key = _autopilot_key(user)
    if action == "stop":
        _stop_email_autopilot_schedule(key)
        return _email_autopilot_schedule_payload(user)
    if action != "start":
        raise ValueError("Unknown schedule action. Use 'start' or 'stop'.")

    sess = state.session(user)
    data_root = _user_data_dir(user["id"]) if user else None
    interval = _bounded_int(
        payload.get("interval_minutes"),
        default=settings.email_autopilot_interval_minutes,
        minimum=5,
        maximum=1440,
    )
    days = _bounded_int(payload.get("days"), default=7, minimum=1, maximum=60)
    limit = _bounded_int(
        payload.get("limit"),
        default=settings.email_sync_limit,
        minimum=1,
        maximum=200,
    )
    db_path = str(_resolve_db_path(str(payload.get("db_path") or sess.last_db_path), data_root))
    run_now = bool(payload.get("run_now", False))
    _start_email_autopilot_schedule(
        key,
        state,
        user,
        db_path=db_path,
        interval_minutes=interval,
        days=days,
        limit=limit,
        run_now=run_now,
    )
    return _email_autopilot_schedule_payload(user)


def _email_autopilot_schedule_payload(user: AuthUser | None = None) -> dict[str, Any]:
    key = _autopilot_key(user)
    with _AUTOPILOT_LOCK:
        entry = _AUTOPILOT_SCHEDULES.get(key)
        if not entry:
            return {
                "ok": True,
                "enabled": False,
                "interval_minutes": settings.email_autopilot_interval_minutes,
            }
        return {
            "ok": True,
            "enabled": True,
            "interval_minutes": entry["interval_minutes"],
            "db_path": entry["db_path"],
            "days": entry["days"],
            "limit": entry["limit"],
            "running": entry.get("running", False),
            "last_run": entry.get("last_run"),
            "last_error": entry.get("last_error"),
            "next_run": entry.get("next_run"),
        }


def _start_email_autopilot_schedule(
    key: int,
    state: WebState,
    user: AuthUser | None,
    *,
    db_path: str,
    interval_minutes: int,
    days: int,
    limit: int,
    run_now: bool,
) -> None:
    _stop_email_autopilot_schedule(key)
    stop_event = threading.Event()
    user_copy = dict(user) if user else None
    now = datetime.now()
    entry: dict[str, Any] = {
        "stop_event": stop_event,
        "interval_minutes": interval_minutes,
        "db_path": db_path,
        "days": days,
        "limit": limit,
        "running": False,
        "last_run": None,
        "last_error": None,
        "next_run": (now if run_now else now + timedelta(minutes=interval_minutes)).isoformat(),
    }
    with _AUTOPILOT_LOCK:
        _AUTOPILOT_SCHEDULES[key] = entry
    thread = threading.Thread(
        target=_email_autopilot_schedule_worker,
        args=(key, state, user_copy, stop_event, run_now),
        daemon=True,
    )
    entry["thread"] = thread
    thread.start()


def _stop_email_autopilot_schedule(key: int) -> None:
    with _AUTOPILOT_LOCK:
        entry = _AUTOPILOT_SCHEDULES.pop(key, None)
    if entry is not None:
        stop = entry.get("stop_event")
        if isinstance(stop, threading.Event):
            stop.set()


def _email_autopilot_schedule_worker(
    key: int,
    state: WebState,
    user: dict[str, Any] | None,
    stop_event: threading.Event,
    run_now: bool,
) -> None:
    if not run_now and stop_event.wait(_schedule_interval_seconds(key)):
        return
    while not stop_event.is_set():
        with _AUTOPILOT_LOCK:
            entry = _AUTOPILOT_SCHEDULES.get(key)
            if entry is None:
                return
            entry["running"] = True
            payload = {
                "db_path": entry["db_path"],
                "days": entry["days"],
                "limit": entry["limit"],
            }
        should_stop = False
        try:
            result = _run_email_autopilot_from_payload(payload, state, user)  # type: ignore[arg-type]
            summary = {
                "sync_updates": len(result.get("sync", {}).get("updates", [])),
                "actions": len(result.get("actions", [])),
            }
            with _AUTOPILOT_LOCK:
                if key in _AUTOPILOT_SCHEDULES:
                    _AUTOPILOT_SCHEDULES[key]["last_error"] = None
                    _AUTOPILOT_SCHEDULES[key]["last_result"] = summary
        except Exception as exc:
            log.exception("[web] scheduled email autopilot failed")
            with _AUTOPILOT_LOCK:
                if key in _AUTOPILOT_SCHEDULES:
                    _AUTOPILOT_SCHEDULES[key]["last_error"] = str(exc)
        finally:
            with _AUTOPILOT_LOCK:
                entry = _AUTOPILOT_SCHEDULES.get(key)
                if entry is None:
                    should_stop = True
                else:
                    interval = int(entry["interval_minutes"])
                    entry["running"] = False
                    entry["last_run"] = datetime.now().isoformat()
                    entry["next_run"] = (datetime.now() + timedelta(minutes=interval)).isoformat()
        if should_stop:
            return
        if stop_event.wait(_schedule_interval_seconds(key)):
            return


def _schedule_interval_seconds(key: int) -> float:
    with _AUTOPILOT_LOCK:
        entry = _AUTOPILOT_SCHEDULES.get(key)
        if entry is None:
            return 0.0
        return float(int(entry["interval_minutes"]) * 60)


def _autopilot_key(user: AuthUser | None) -> int:
    return int(user["id"]) if user else 0


def _safe_email_audit_payload(
    email_result: dict[str, Any],
    account_source: str,
) -> dict[str, Any]:
    return {
        "account_source": account_source,
        "sent": bool(email_result.get("sent")),
        "dry_run": bool(email_result.get("dry_run")),
        "recipient": str(email_result.get("recipient") or ""),
        "subject": str(email_result.get("subject") or ""),
        "attachments": list(email_result.get("attachments") or []),
    }


def _safe_sync_audit_payload(
    sync_result: dict[str, Any],
    account_source: str,
) -> dict[str, Any]:
    return {
        "account_source": account_source,
        "dry_run": bool(sync_result.get("dry_run")),
        "seen": int(sync_result.get("seen") or 0),
        "ignored": int(sync_result.get("ignored") or 0),
        "classified": int(sync_result.get("classified") or 0),
        "matched": int(sync_result.get("matched") or 0),
        "updates": len(sync_result.get("updates") or []),
        "unmatched": list(sync_result.get("unmatched") or [])[:3],
    }


def _inbox_root(user: AuthUser | None) -> Path:
    return _user_data_dir(user["id"]) if user else DATA_DIR


def _inbox_payload(state: WebState, user: AuthUser | None = None) -> dict[str, Any]:
    """All remembered URLs/ads for this account (newest first)."""
    from job_agent.tools.inbox import inbox_path, load_inbox

    return {"ok": True, "items": load_inbox(inbox_path(_inbox_root(user)))}


def _inbox_add_from_payload(
    payload: dict[str, Any], state: WebState, user: AuthUser | None = None
) -> dict[str, Any]:
    from job_agent.tools.inbox import add_item, inbox_path, load_inbox

    path = inbox_path(_inbox_root(user))
    item = add_item(path, str(payload.get("url") or ""), note=str(payload.get("note") or ""))
    return {"ok": True, "item": item, "items": load_inbox(path)}


def _inbox_update_from_payload(
    payload: dict[str, Any], state: WebState, user: AuthUser | None = None
) -> dict[str, Any]:
    from job_agent.tools.inbox import inbox_path, load_inbox, remove_item, update_status

    path = inbox_path(_inbox_root(user))
    item_id = str(payload.get("id") or "").strip()
    if not item_id:
        raise ValueError("id is required")
    action = str(payload.get("action") or "status").strip().lower()
    if action == "remove":
        if not remove_item(path, item_id):
            raise ValueError(f"Inbox-Eintrag '{item_id}' nicht gefunden.")
    else:
        update_status(path, item_id, str(payload.get("status") or "neu"))
    return {"ok": True, "items": load_inbox(path)}


def _inbox_evaluate_from_payload(
    payload: dict[str, Any], state: WebState, user: AuthUser | None = None
) -> dict[str, Any]:
    """Paste-a-JD auto-pipeline: text -> JobPosting -> Matcher -> Writer -> Tracker."""
    from job_agent.tools.inbox import (
        evaluate_pasted_job,
        inbox_path,
        posting_from_text,
        update_status,
    )

    sess = state.session(user)
    data_root = _user_data_dir(user["id"]) if user else None
    db_path = _resolve_db_path(str(payload.get("db_path") or sess.last_db_path), data_root)
    threshold = _bounded_float(payload.get("threshold"), default=0.5, minimum=0.0, maximum=1.0)
    use_llm = bool(payload.get("llm", False))

    with state.lock:
        profile = sess.current_profile
    if profile is None:
        profile = demo_profile()

    posting = posting_from_text(
        title=str(payload.get("title") or ""),
        company=str(payload.get("company") or ""),
        location=str(payload.get("location") or ""),
        description=str(payload.get("description") or ""),
        url=str(payload.get("url") or ""),
    )

    store = Store(db_path)
    try:
        match, application = evaluate_pasted_job(
            store, profile, posting, threshold=threshold, use_llm=use_llm
        )
        statuses = store.all_status()
        liveness = store.all_liveness()
        applications = [
            _application_payload(app, statuses)
            for item in statuses
            if (app := store.get_application(item.job_id))
        ]
    finally:
        store.close()

    inbox_id = str(payload.get("inbox_id") or "").strip()
    if inbox_id:
        try:
            update_status(inbox_path(_inbox_root(user)), inbox_id, "bewertet", job_id=posting.id)
        except ValueError:
            pass

    # Surface the evaluated job in the Suche view: merge into the session result.
    with state.lock:
        if sess.last_result is None:
            sess.last_result = PipelineResult()
        sess.last_result.jobs = [job for job in sess.last_result.jobs if job.id != posting.id]
        sess.last_result.matches = [m for m in sess.last_result.matches if m.job_id != posting.id]
        sess.last_result.jobs.insert(0, posting)
        sess.last_result.matches.insert(0, match)
        if application is not None:
            sess.last_result.applications = [
                app for app in sess.last_result.applications if app.job_id != posting.id
            ]
            sess.last_result.applications.append(application)
        sess.last_db_path = str(db_path)

    return {
        "ok": True,
        "job": _job_payload(posting, [match], statuses, liveness),
        "application": _application_payload(application, statuses) if application else None,
        "applications": applications,
        "threshold": threshold,
    }


def _patterns_payload(
    params: dict[str, list[str]], state: WebState, user: AuthUser | None = None
) -> dict[str, Any]:
    """Tracker-Muster: Funnel, Quoten, Antwortzeiten, überfällige Bewerbungen."""
    from job_agent.tools.patterns import analyze_patterns

    sess = state.session(user)
    data_root = _user_data_dir(user["id"]) if user else None
    db_path = _resolve_db_path(params.get("db_path", [sess.last_db_path])[0], data_root)
    store = Store(db_path)
    try:
        return analyze_patterns(store)
    finally:
        store.close()


def _interview_prep_payload(
    params: dict[str, list[str]], state: WebState, user: AuthUser | None = None
) -> dict[str, Any]:
    """Per-job interview guide (deterministic core, optional LLM extras)."""
    from job_agent.agents.interview_prep import build_interview_prep

    sess = state.session(user)
    data_root = _user_data_dir(user["id"]) if user else None
    job_id = params.get("job_id", [""])[0].strip()
    if not job_id:
        raise ValueError("job_id is required")
    use_llm = params.get("llm", ["0"])[0].lower() in {"1", "true", "yes"}
    db_path = _resolve_db_path(params.get("db_path", [sess.last_db_path])[0], data_root)

    with state.lock:
        profile = sess.current_profile
        last_result = sess.last_result
        sess.last_db_path = str(db_path)
    state_job = None
    if last_result is not None:
        state_job = next((item for item in last_result.jobs if item.id == job_id), None)

    store = Store(db_path)
    try:
        job = store.get_job(job_id) or state_job
        if job is not None and state_job is not None:
            store.save_job(job)
    finally:
        store.close()
    if job is None:
        raise ValueError(f"Job '{job_id}' not found in current search or store.")
    if profile is None:
        profile = demo_profile()
    match = None
    if last_result is not None:
        match = next((m for m in last_result.matches if m.job_id == job_id), None)

    return {"ok": True, "prep": build_interview_prep(job, profile, match=match, use_llm=use_llm)}


def _export_report_from_payload(
    payload: dict[str, Any], state: WebState, user: AuthUser | None = None
) -> dict[str, Any]:
    """Write the per-job Markdown evaluation report and hand back a download link."""
    from job_agent.tools.report import REPORT_FILENAME, evaluation_report_md

    sess = state.session(user)
    data_root = _user_data_dir(user["id"]) if user else None
    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("job_id is required")
    db_path = _resolve_db_path(str(payload.get("db_path") or sess.last_db_path), data_root)

    with state.lock:
        last_result = sess.last_result
        sess.last_db_path = str(db_path)
    state_job = None
    if last_result is not None:
        state_job = next((item for item in last_result.jobs if item.id == job_id), None)

    store = Store(db_path)
    try:
        job = store.get_job(job_id) or state_job
        if job is None:
            raise ValueError(f"Job '{job_id}' not found in current search or store.")
        if state_job is not None:
            store.save_job(job)
        application = store.get_application(job_id)
        status = store.get_status(job_id)
        liveness = store.get_liveness(job_id)
    finally:
        store.close()
    match = None
    if last_result is not None:
        match = next((m for m in last_result.matches if m.job_id == job_id), None)

    report_md = evaluation_report_md(
        job, match=match, application=application, status=status, liveness=liveness
    )
    out_dir = _output_dir(data_root, job_id)
    (out_dir / REPORT_FILENAME).write_text(report_md, encoding="utf-8")
    download = f"/api/download?job_id={quote(job_id)}&file={quote(REPORT_FILENAME)}"
    return {"ok": True, "file": REPORT_FILENAME, "download": download}


def _generate_draft_from_payload(
    payload: dict[str, Any], state: WebState, user: AuthUser | None = None
) -> dict[str, Any]:
    """Create a cover-letter draft for one selected job on demand."""
    from job_agent.agents.matcher import run_matcher
    from job_agent.agents.tracker import run_tracker
    from job_agent.agents.writer import run_writer

    sess = state.session(user)
    data_root = _user_data_dir(user["id"]) if user else None
    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("job_id is required")
    db_path = _resolve_db_path(str(payload.get("db_path") or sess.last_db_path), data_root)

    with state.lock:
        profile = sess.current_profile or demo_profile()
        last_result = sess.last_result
    job = None
    match = None
    if last_result is not None:
        job = next((item for item in last_result.jobs if item.id == job_id), None)
        match = next((item for item in last_result.matches if item.job_id == job_id), None)

    store = Store(db_path)
    try:
        stored_job = store.get_job(job_id)
        job = stored_job or job
        if job is None:
            raise ValueError(f"Job '{job_id}' not found in store.")
        if match is None:
            match = run_matcher([job], profile, threshold=0.0, use_llm=False)[0]
        application = run_writer(
            job=job,
            match=match,
            profile=profile,
            use_llm=bool(payload.get("llm", False)),
        )
        store.save_job(job)
        status = run_tracker(application=application, store=store, status="draft")
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
        if sess.last_result is None:
            sess.last_result = PipelineResult()
        if not any(item.id == job.id for item in sess.last_result.jobs):
            sess.last_result.jobs.append(job)
        sess.last_result.matches = [
            item for item in sess.last_result.matches if item.job_id != match.job_id
        ]
        sess.last_result.matches.append(match)
        sess.last_result.applications = [
            item for item in sess.last_result.applications if item.job_id != application.job_id
        ]
        sess.last_result.applications.append(application)
        sess.last_result.statuses = [
            item for item in sess.last_result.statuses if item.job_id != status.job_id
        ]
        sess.last_result.statuses.append(status)

    return {
        "ok": True,
        "application": _application_payload(application, [status]),
        "applications": applications,
        "job": _job_payload(job, [match], [status]),
    }


def _check_liveness_from_payload(
    payload: dict[str, Any], state: WebState, user: AuthUser | None = None
) -> dict[str, Any]:
    from job_agent.tools.liveness import check_liveness

    sess = state.session(user)
    data_root = _user_data_dir(user["id"]) if user else None
    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("job_id is required")
    deep = bool(payload.get("deep", settings.liveness_deep))
    db_path = _resolve_db_path(str(payload.get("db_path") or sess.last_db_path), data_root)
    store = Store(db_path)
    try:
        job = store.get_job(job_id)
        if job is None:
            raise ValueError(f"Job '{job_id}' not found in store.")
        result = check_liveness(str(job.url), deep=deep)
        store.save_liveness(job_id, result)
    finally:
        store.close()

    with state.lock:
        sess.last_db_path = str(db_path)

    return {"ok": True, "job_id": job_id, "liveness": result.model_dump(mode="json")}


ALLOWED_EXPORT_SUFFIXES = {".pdf", ".json", ".zip", ".md"}


def _output_dir(data_root: Path | None, job_id: str) -> Path:
    """Per-user export directory for one application, confined under the data root."""
    from job_agent.tools.export import _safe_slug

    base = ((data_root or DATA_DIR) / "output").resolve(strict=False)
    out = (base / _safe_slug(job_id)).resolve(strict=False)
    if out != base and base not in out.parents:
        raise ValueError("Invalid export path.")
    out.mkdir(parents=True, exist_ok=True)
    return out


def _application_cv_path(
    state: WebState,
    user: AuthUser | None,
    data_root: Path | None,
    job_id: str,
) -> Path:
    uploaded = _uploaded_cv_path(state, user)
    out_dir = _output_dir(data_root, job_id)
    if uploaded is not None:
        suffix = uploaded.suffix.lower()
        target = out_dir / ("lebenslauf.pdf" if suffix == ".pdf" else f"lebenslauf{suffix}")
        shutil.copyfile(uploaded, target)
        return target

    from job_agent.tools.export import _render_cv

    sess = state.session(user)
    with state.lock:
        cv_profile = sess.current_profile
    cv_path = out_dir / "lebenslauf.pdf"
    _render_cv(cv_path, cv_profile or demo_profile())
    return cv_path


def _export_application_from_payload(
    payload: dict[str, Any], state: WebState, user: AuthUser | None = None
) -> dict[str, Any]:
    from job_agent.tools.export import export_application

    sess = state.session(user)
    data_root = _user_data_dir(user["id"]) if user else None
    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("job_id is required")

    db_path = _resolve_db_path(str(payload.get("db_path") or sess.last_db_path), data_root)
    store = Store(db_path)
    try:
        job = store.get_job(job_id)
        application = store.get_application(job_id)
    finally:
        store.close()
    if job is None:
        raise ValueError(f"Job '{job_id}' not found in store.")
    if application is None:
        raise ValueError(f"No drafted application exists for job '{job_id}'.")

    with state.lock:
        profile = sess.current_profile
        last_result = sess.last_result
        sess.last_db_path = str(db_path)
    if profile is None:
        profile = demo_profile()
    match = None
    if last_result is not None:
        match = next((m for m in last_result.matches if m.job_id == job_id), None)

    out_dir = _output_dir(data_root, job_id)
    result = export_application(
        job,
        application,
        profile,
        out_dir=out_dir,
        match=match,
        cv_source_path=_uploaded_cv_path(state, user),
    )
    download = f"/api/download?job_id={quote(job_id)}&file={quote(result.zip_name)}"
    return {
        "ok": True,
        "job_id": job_id,
        "files": [*result.files, result.zip_name],
        "zip_name": result.zip_name,
        "download": download,
    }


def _download_path(user: AuthUser | None, job_id: str, filename: str) -> Path:
    """Resolve a download to a single file inside the user's export directory."""
    if not job_id or not filename:
        raise ValueError("job_id and file are required")
    data_root = _user_data_dir(user["id"]) if user else None
    safe_name = Path(filename).name
    if Path(safe_name).suffix.lower() not in ALLOWED_EXPORT_SUFFIXES:
        raise ValueError("Unsupported download type.")
    out_dir = _output_dir(data_root, job_id)
    path = (out_dir / safe_name).resolve(strict=False)
    if out_dir not in path.parents:
        raise ValueError("Invalid download path.")
    if not path.is_file():
        raise FileNotFoundError("Datei nicht gefunden — bitte zuerst das Export-Paket erstellen.")
    return path


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


def _safe_liveness(db_path: str, data_root: Path | None = None) -> dict[str, LivenessResult]:
    try:
        store = Store(_resolve_db_path(db_path, data_root))
        try:
            return store.all_liveness()
        finally:
            store.close()
    except Exception:
        return {}


def _safe_jobs(db_path: str, data_root: Path | None = None) -> list[JobPosting]:
    try:
        store = Store(_resolve_db_path(db_path, data_root))
        try:
            return store.all_jobs()
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


def _summary_from_state(
    jobs: list[JobPosting],
    matches: list[MatchResult],
    applications: list[dict[str, Any]],
    statuses: list[ApplicationStatus],
) -> dict[str, int]:
    return {
        "jobs": len(jobs),
        "matches": len(matches),
        "drafts": len(applications),
        "tracked": len(statuses),
    }


def _job_payload(
    job: JobPosting,
    matches: list[MatchResult],
    statuses: list[ApplicationStatus],
    liveness: dict[str, LivenessResult] | None = None,
) -> dict[str, Any]:
    match = next((item for item in matches if item.job_id == job.id), None)
    status = next((item for item in statuses if item.job_id == job.id), None)
    live = (liveness or {}).get(job.id)
    recipients = recipient_payload(job)
    return {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "source": job.source,
        "source_label": _source_label(job.source),
        "contact_email": recipients["contact_email"],
        "recipient_suggestions": recipients["recipient_suggestions"],
        "recipient_confidence": recipients["recipient_confidence"],
        "liveness": live.model_dump(mode="json") if live else None,
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


def _extract_contact_email(job: JobPosting) -> str:
    """Best-effort contact/apply email parsed from the posting text (else empty)."""
    return best_recipient(job)


def _source_label(source: str) -> str:
    return {
        "adzuna": "Adzuna",
        "ba-jobsuche": "Arbeitsagentur",
        "stepstone": "StepStone",
        "linkedin": "LinkedIn",
        "indeed": "Indeed",
        "xing": "XING",
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
