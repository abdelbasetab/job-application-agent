"""Local readiness diagnosis — `job-agent doctor`.

Checks that the things this private, local tool needs are actually present and
configured: writable data directories, the SQLite stores, LLM/email config, and
the optional binaries/dependencies (Tesseract OCR, Playwright, PDF export). Each
check returns a structured OK / WARN / FAIL with a concrete fix, never a raw
stack trace. WARN = an optional feature won't work; FAIL = a core path is broken.
"""

from __future__ import annotations

import importlib.util
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from job_agent.utils.config import settings

Status = Literal["ok", "warn", "fail"]


@dataclass(frozen=True)
class Check:
    """One readiness check result."""

    name: str
    status: Status
    detail: str
    fix: str = ""


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".doctor_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def run_doctor() -> list[Check]:
    """Run every readiness check and return the structured results."""
    checks: list[Check] = []
    checks.append(_check_data_dir())
    checks.append(_check_sqlite())
    checks.append(_check_llm())
    checks.append(_check_smtp())
    checks.append(_check_imap())
    checks.extend(_check_cv_dependencies())
    checks.append(_check_pdf_export())
    checks.append(_check_playwright())
    checks.append(_check_web_assets())
    checks.append(_check_web_auth())
    checks.append(_check_network_policy())
    checks.append(_check_lockfiles())
    checks.append(_check_env_file())
    return checks


def worst_status(checks: list[Check]) -> Status:
    """The most severe status across all checks (for the process exit code)."""
    if any(c.status == "fail" for c in checks):
        return "fail"
    if any(c.status == "warn" for c in checks):
        return "warn"
    return "ok"


def _data_dir() -> Path:
    # Import lazily so `doctor` does not pull in the web server stack eagerly.
    from job_agent.web import DATA_DIR

    return DATA_DIR


def _check_data_dir() -> Check:
    data_dir = _data_dir()
    if _writable_dir(data_dir):
        return Check("Datenverzeichnis", "ok", f"Schreibbar: {data_dir}")
    return Check(
        "Datenverzeichnis",
        "fail",
        f"Nicht schreibbar: {data_dir}",
        fix="Schreibrechte prüfen oder JOB_AGENT_DATA_DIR auf einen schreibbaren Pfad setzen.",
    )


def _check_sqlite() -> Check:
    db_path = Path(settings.sqlite_path)
    parent = db_path if db_path.is_absolute() else (_data_dir().parent / db_path)
    if _writable_dir(parent.parent):
        return Check("SQLite-Speicher", "ok", f"DB-Verzeichnis schreibbar: {parent.parent}")
    return Check(
        "SQLite-Speicher",
        "fail",
        f"DB-Verzeichnis nicht schreibbar: {parent.parent}",
        fix="SQLITE_PATH auf einen schreibbaren Pfad setzen.",
    )


def _check_llm() -> Check:
    from job_agent.utils.llm import validate_llm_base_url

    provider = settings.llm_provider.lower()
    if provider not in {"ollama", "openai", "kiconnect", "anthropic", "groq"}:
        return Check(
            "LLM-Konfiguration",
            "fail",
            f"Unbekannter Provider: {settings.llm_provider}",
            fix="LLM_PROVIDER auf ollama, openai, kiconnect, anthropic oder groq setzen.",
        )
    if settings.llm_base_url:
        try:
            validate_llm_base_url(
                settings.llm_base_url,
                provider,
                settings.llm_api_key,
            )
        except ValueError as exc:
            return Check(
                "LLM-Konfiguration",
                "fail",
                str(exc),
                fix="Remote LLM-Endpunkte per HTTPS anbinden; lokales HTTP nur bewusst verwenden.",
            )
    if provider == "ollama":
        return Check("LLM-Konfiguration", "ok", "Provider=ollama (kein API-Key nötig).")
    if not settings.llm_api_key:
        return Check(
            "LLM-Konfiguration",
            "fail" if settings.enable_llm_agents else "warn",
            f"Provider={settings.llm_provider}, aber kein API-Key gesetzt.",
            fix="OPENAI_API_KEY (openai/kiconnect), ANTHROPIC_API_KEY oder GROQ_API_KEY in .env setzen.",
        )
    if provider == "kiconnect" and not settings.llm_base_url:
        return Check(
            "LLM-Konfiguration",
            "warn",
            "Provider=kiconnect, aber LLM_BASE_URL fehlt.",
            fix="LLM_BASE_URL auf die OpenAI-kompatible Gateway-URL (…/v1) setzen.",
        )
    return Check(
        "LLM-Konfiguration",
        "ok",
        f"Provider={settings.llm_provider}, Modell={settings.llm_model}.",
    )


def _check_smtp() -> Check:
    if settings.email_dry_run:
        return Check("E-Mail-Versand (SMTP)", "ok", "EMAIL_DRY_RUN=true — Versand wird nur simuliert.")
    if not settings.email_use_tls:
        return Check(
            "E-Mail-Versand (SMTP)",
            "fail",
            "EMAIL_DRY_RUN=false, aber SMTP-TLS ist deaktiviert.",
            fix="EMAIL_USE_TLS=true setzen; Port 465 nutzt implizites TLS, andere Ports STARTTLS.",
        )
    if not all(
        (
            settings.email_smtp_host,
            settings.email_smtp_user,
            settings.email_smtp_password,
            settings.email_from,
        )
    ):
        return Check(
            "E-Mail-Versand (SMTP)",
            "fail",
            "EMAIL_DRY_RUN=false, aber SMTP Host/User/Passwort/Absender sind unvollständig.",
            fix="EMAIL_SMTP_HOST/USER/PASSWORD setzen oder EMAIL_DRY_RUN=true lassen.",
        )
    return Check("E-Mail-Versand (SMTP)", "ok", f"SMTP konfiguriert: {settings.email_smtp_host}")


def _check_imap() -> Check:
    configured = bool(
        settings.email_imap_host and settings.email_imap_user and settings.email_imap_password
    )
    if configured:
        return Check("Inbox-Sync (IMAP)", "ok", f"IMAP konfiguriert: {settings.email_imap_host}")
    return Check(
        "Inbox-Sync (IMAP)",
        "fail" if not settings.email_sync_dry_run else "warn",
        "IMAP-Zugangsdaten unvollständig — automatische Status-Updates aus der Inbox deaktiviert.",
        fix="EMAIL_IMAP_HOST/USER/PASSWORD setzen (optionales Feature).",
    )


def _check_cv_dependencies() -> list[Check]:
    checks: list[Check] = []
    if _module_available("pdfplumber"):
        checks.append(Check("PDF-Lesen (pdfplumber)", "ok", "Verfügbar."))
    else:
        checks.append(
            Check(
                "PDF-Lesen (pdfplumber)",
                "fail",
                "pdfplumber fehlt — PDF-Lebensläufe können nicht gelesen werden.",
                fix="uv pip install pdfplumber",
            )
        )
    if _module_available("pypdfium2"):
        checks.append(Check("Scan-OCR (PDF-Renderer)", "ok", "pypdfium2 verfügbar."))
    else:
        checks.append(
            Check(
                "Scan-OCR (PDF-Renderer)",
                "warn",
                "pypdfium2 fehlt — gescannte Bild-PDFs können nicht gerendert werden.",
                fix="Die gesperrten Projektabhängigkeiten neu installieren (pdfplumber bringt den Renderer mit).",
            )
        )
    if shutil.which("tesseract"):
        checks.append(Check("Scan-OCR (Tesseract)", "ok", "tesseract auf PATH."))
    else:
        checks.append(
            Check(
                "Scan-OCR (Tesseract)",
                "warn",
                "tesseract nicht auf PATH — OCR für gescannte CVs nicht möglich.",
                fix="Tesseract installieren (Windows: UB-Mannheim-Build) und auf PATH legen.",
            )
        )
    if _module_available("docx"):
        checks.append(Check("DOCX-Lesen (python-docx)", "ok", "Verfügbar."))
    else:
        checks.append(
            Check(
                "DOCX-Lesen (python-docx)",
                "warn",
                "python-docx fehlt — .docx-Lebensläufe nicht lesbar (PDF/TXT/MD gehen).",
                fix="uv pip install python-docx",
            )
        )
    return checks


def _check_pdf_export() -> Check:
    if _module_available("fpdf"):
        return Check("PDF-Export (fpdf2)", "ok", "fpdf2 verfügbar.")
    return Check(
        "PDF-Export (fpdf2)",
        "warn",
        "fpdf2 fehlt — PDF-/Export-Paket für Bewerbungen deaktiviert.",
        fix="uv pip install fpdf2",
    )


def _check_playwright() -> Check:
    if _module_available("playwright"):
        return Check(
            "Liveness-Tiefencheck (Playwright)",
            "ok",
            "Playwright verfügbar (Browser-Fallback für Liveness möglich).",
        )
    return Check(
        "Liveness-Tiefencheck (Playwright)",
        "warn",
        "Playwright fehlt — Liveness nutzt nur den leichten HTTP-Check (ausreichend für die meisten Fälle).",
        fix="uv sync --locked --extra liveness && uv run playwright install chromium",
    )


def _check_web_assets() -> Check:
    from job_agent.web import STATIC_DIR

    if (STATIC_DIR / "index.html").exists():
        return Check("Web-UI-Assets", "ok", f"Statische Dateien vorhanden: {STATIC_DIR}")
    return Check(
        "Web-UI-Assets",
        "fail",
        f"index.html fehlt unter {STATIC_DIR}.",
        fix="Installation prüfen — web_static/ muss mit dem Paket ausgeliefert werden.",
    )


def _check_env_file() -> Check:
    from job_agent.utils.config import _REPO_ROOT

    if (_REPO_ROOT / ".env").exists():
        return Check(".env-Datei", "ok", ".env gefunden.")
    return Check(
        ".env-Datei",
        "warn",
        "Keine .env gefunden — es gelten Standardwerte (Offline-Demo funktioniert trotzdem).",
        fix="cp .env.example .env und Werte eintragen.",
    )


def _check_web_auth() -> Check:
    """Ensure a fresh closed-registration deployment can actually be entered."""
    if settings.web_allow_registration:
        return Check(
            "Web-Registrierung",
            "warn",
            "WEB_ALLOW_REGISTRATION=true — jeder erreichbare Besucher kann ein Konto anlegen.",
            fix="Nach der kontrollierten Einrichtung WEB_ALLOW_REGISTRATION=false setzen.",
        )
    if settings.web_bootstrap_email or settings.web_bootstrap_password:
        if not (settings.web_bootstrap_email and settings.web_bootstrap_password):
            return Check(
                "Web-Bootstrap",
                "fail",
                "Nur einer der beiden Bootstrap-Werte ist gesetzt.",
                fix="WEB_BOOTSTRAP_EMAIL und WEB_BOOTSTRAP_PASSWORD gemeinsam setzen oder beide entfernen.",
            )
        if len(settings.web_bootstrap_password) < 12:
            return Check(
                "Web-Bootstrap",
                "fail",
                "Das Bootstrap-Passwort ist kürzer als 12 Zeichen.",
                fix="Ein langes zufälliges Bootstrap-Passwort über den Secret Manager setzen.",
            )
        return Check("Web-Bootstrap", "ok", "Geschlossene Registrierung mit Bootstrap-Konto.")

    from job_agent.web import AUTH_DB_PATH

    if AUTH_DB_PATH.exists():
        try:
            conn = sqlite3.connect(f"file:{AUTH_DB_PATH.as_posix()}?mode=ro", uri=True)
            try:
                count = int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
            finally:
                conn.close()
            if count:
                return Check(
                    "Web-Bootstrap",
                    "ok",
                    "Registrierung geschlossen; mindestens ein bestehendes Konto vorhanden.",
                )
        except (OSError, sqlite3.Error):
            pass
    return Check(
        "Web-Bootstrap",
        "fail",
        "Registrierung ist geschlossen, aber weder Konto noch Bootstrap-Zugang ist erkennbar.",
        fix="WEB_BOOTSTRAP_EMAIL und WEB_BOOTSTRAP_PASSWORD für den ersten Start sicher setzen.",
    )


def _check_network_policy() -> Check:
    if settings.allow_private_network_services:
        return Check(
            "Netzwerk-Zielschutz",
            "warn",
            "Private/Loopback-Dienste sind ausdrücklich erlaubt; SSRF-Schutz ist reduziert.",
            fix="ALLOW_PRIVATE_NETWORK_SERVICES=false lassen, außer für einen kontrollierten lokalen Dienst.",
        )
    oauth_configured = bool(
        settings.email_oauth_google_client_id or settings.email_oauth_microsoft_client_id
    )
    if oauth_configured and not settings.email_oauth_redirect_base:
        return Check(
            "OAuth-Redirect",
            "fail",
            "OAuth-Client ist gesetzt, aber EMAIL_OAUTH_REDIRECT_BASE fehlt.",
            fix="Die explizite externe HTTPS-Origin als EMAIL_OAUTH_REDIRECT_BASE setzen.",
        )
    if settings.email_oauth_redirect_base:
        parsed = urlsplit(settings.email_oauth_redirect_base)
        local = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if parsed.scheme != "https" and not local:
            return Check(
                "OAuth-Redirect",
                "fail",
                "Die externe OAuth-Basis verwendet kein HTTPS.",
                fix="EMAIL_OAUTH_REDIRECT_BASE auf die öffentliche HTTPS-Origin setzen.",
            )
    if settings.web_host in {"0.0.0.0", "::"} and not settings.web_secure_cookies:
        return Check(
            "Web-Cookies",
            "warn",
            "Server bindet breit, aber Secure-Cookies sind aus.",
            fix="Hinter HTTPS WEB_SECURE_COOKIES=true setzen; lokal nur an 127.0.0.1 binden.",
        )
    if settings.web_host in {"127.0.0.1", "localhost", "::1"} and settings.web_secure_cookies:
        return Check(
            "Web-Cookies",
            "warn",
            "Secure-Cookies sind bei lokaler Bindung aktiv und funktionieren über reines HTTP nicht.",
            fix="Lokal WEB_SECURE_COOKIES=false oder auch lokal HTTPS verwenden.",
        )
    return Check("Netzwerk-Zielschutz", "ok", "Private Ziele gesperrt; Cookie/Redirect-Basis plausibel.")


def _check_lockfiles() -> Check:
    from job_agent.utils.config import _REPO_ROOT

    missing = [
        name
        for name in ("uv.lock", "requirements-runtime.lock")
        if not (_REPO_ROOT / name).is_file()
    ]
    if not missing:
        return Check("Dependency-Lockfiles", "ok", "uv.lock und Runtime-Export vorhanden.")
    return Check(
        "Dependency-Lockfiles",
        "warn",
        "Fehlend: " + ", ".join(missing),
        fix="uv lock und danach den dokumentierten uv export ausführen.",
    )
