"""Tiny env config helper — loads .env and exposes the few keys the app uses."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env", override=False)


class Settings:
    """A flat settings facade — no fancy validation, this is Sprint 1."""

    # LLM provider — one of: "ollama" (default), "openai", "kiconnect",
    # "anthropic", "groq". "openai" and "kiconnect" are OpenAI-compatible and
    # share OPENAI_API_KEY + LLM_BASE_URL (KI-Connect = a hosted OpenAI gateway).
    llm_provider: str = os.getenv("LLM_PROVIDER", "ollama")
    llm_model: str = os.getenv("LLM_MODEL", "qwen2.5:7b-instruct")
    llm_temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.2"))
    llm_call_timeout: float = float(os.getenv("LLM_CALL_TIMEOUT", "45"))
    # Optional custom endpoint — used by Ollama (http://localhost:11434) or self-hosted gateways.
    llm_base_url: str | None = os.getenv("LLM_BASE_URL") or None
    enable_llm_agents: bool = os.getenv("ENABLE_LLM_AGENTS", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    enable_chroma: bool = os.getenv("ENABLE_CHROMA", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    # Provider keys
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    groq_api_key: str | None = os.getenv("GROQ_API_KEY")

    # Job APIs
    adzuna_app_id: str | None = os.getenv("ADZUNA_APP_ID")
    adzuna_app_key: str | None = os.getenv("ADZUNA_APP_KEY")
    adzuna_country: str = os.getenv("ADZUNA_COUNTRY", "de")
    ba_jobsuche_base_url: str = os.getenv(
        "BA_JOBSUCHE_BASE_URL",
        "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4",
    )
    # Public, fixed API key the BA-Jobsuche API requires on every request.
    # Same value for everyone; without it the server returns 403.
    ba_jobsuche_api_key: str = os.getenv("BA_JOBSUCHE_API_KEY", "jobboerse-jobsuche")

    # Storage
    sqlite_path: str = os.getenv("SQLITE_PATH", "./data/job_agent.db")
    chroma_path: str = os.getenv("CHROMA_PATH", "./data/chroma_db")

    # Web UI / multi-user server
    web_host: str = os.getenv("WEB_HOST", "127.0.0.1")
    web_port: int = int(os.getenv("WEB_PORT", "7860"))
    # Set true only when serving over HTTPS — Secure cookies are not sent over
    # plain http://127.0.0.1, which would break purely local use.
    web_secure_cookies: bool = os.getenv("WEB_SECURE_COOKIES", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    # Optional real embeddings via the OpenAI-compatible gateway (e.g. KI-Connect).
    # A model the gateway exposes, e.g. "Qwen 3 Embedding 8B".
    # Empty -> ProfileVectorStore uses offline hash embeddings.
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "")

    # Optional polite detail-page scraper (ADR-0005), off by default.
    enable_scraper: bool = os.getenv("ENABLE_SCRAPER", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    scraper_min_interval: float = float(os.getenv("SCRAPER_MIN_INTERVAL", "2.0"))

    # Optional SMTP submission for Tracker. Dry-run is the safe default.
    email_smtp_host: str | None = os.getenv("EMAIL_SMTP_HOST") or None
    email_smtp_port: int = int(os.getenv("EMAIL_SMTP_PORT", "587"))
    email_smtp_user: str | None = os.getenv("EMAIL_SMTP_USER") or None
    email_smtp_password: str | None = os.getenv("EMAIL_SMTP_PASSWORD") or None
    email_from: str | None = os.getenv("EMAIL_FROM") or None
    email_demo_recipient: str | None = os.getenv("EMAIL_DEMO_RECIPIENT") or None
    email_use_tls: bool = os.getenv("EMAIL_USE_TLS", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    email_dry_run: bool = os.getenv("EMAIL_DRY_RUN", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    email_imap_host: str | None = os.getenv("EMAIL_IMAP_HOST") or None
    email_imap_port: int = int(os.getenv("EMAIL_IMAP_PORT", "993"))
    email_imap_user: str | None = os.getenv("EMAIL_IMAP_USER") or email_smtp_user
    email_imap_password: str | None = os.getenv("EMAIL_IMAP_PASSWORD") or email_smtp_password
    email_imap_folder: str = os.getenv("EMAIL_IMAP_FOLDER", "INBOX")
    email_sync_dry_run: bool = os.getenv("EMAIL_SYNC_DRY_RUN", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    email_sync_limit: int = int(os.getenv("EMAIL_SYNC_LIMIT", "50"))

    @property
    def llm_api_key(self) -> str | None:
        """Return the API key for the configured provider (None for Ollama)."""
        provider = self.llm_provider.lower()
        if provider in {"openai", "kiconnect"}:
            return self.openai_api_key
        if provider == "anthropic":
            return self.anthropic_api_key
        if provider == "groq":
            return self.groq_api_key
        return None  # ollama needs no key

    def startup_warnings(self) -> list[str]:
        """Misconfiguration that would only surface as a runtime failure.

        Returned (not raised) so the server still starts — the offline demo and
        deterministic fallbacks keep working — but the operator is told what
        will not work until the relevant variables are set.
        """
        warnings: list[str] = []
        provider = self.llm_provider.lower()
        if provider != "ollama" and not self.llm_api_key:
            warnings.append(
                f"LLM_PROVIDER={self.llm_provider} aber kein API-Key gesetzt — "
                "LLM-Agenten/CV-Reader funktionieren erst mit Key."
            )
        if provider == "kiconnect" and not self.llm_base_url:
            warnings.append("LLM_PROVIDER=kiconnect benötigt LLM_BASE_URL (OpenAI-kompatibel).")
        if not self.email_dry_run and not self.email_smtp_host:
            warnings.append(
                "EMAIL_DRY_RUN=false, aber EMAIL_SMTP_HOST fehlt — E-Mail-Versand schlägt fehl."
            )
        if not self.email_sync_dry_run and not (
            self.email_imap_host and self.email_imap_user and self.email_imap_password
        ):
            warnings.append(
                "EMAIL_SYNC_DRY_RUN=false, aber IMAP-Zugangsdaten sind unvollständig — "
                "Inbox-Sync schlägt fehl."
            )
        if self.web_secure_cookies and self.web_host in {"127.0.0.1", "localhost"}:
            warnings.append(
                "WEB_SECURE_COOKIES=true mit lokalem Host — Secure-Cookies werden über "
                "http://127.0.0.1 nicht gesendet, der Login würde scheitern."
            )
        return warnings


settings = Settings()
