# Job Application Agent

**Abgabeversion 1.0.0**

Ein mehrbenutzerfähiger Bewerbungsassistent für den Ablauf **finden → bewerten →
Anschreiben entwerfen → nachverfolgen**. Das Projekt kombiniert deterministische
Regeln, optionale LLM-Agenten, SQLite-Persistenz und eine lokale Weboberfläche.

Wichtig: Das System verschickt standardmäßig keine echten E-Mails und bewirbt
sich nie automatisch. LLM-Ausgaben und Empfänger müssen vor Verwendung geprüft
werden.

## Funktionsumfang

| Bereich | Verhalten |
| --- | --- |
| Profiler | Liest PDF, DOCX, TXT oder Markdown; validiert Dateityp, Größe und Struktur; extrahiert ein typisiertes Profil. |
| Scout | Nutzt Adzuna und BA-Jobsuche, validiert und dedupliziert quellenübergreifend; generative Ausgaben dürfen keine Quelldatensätze erzeugen. Ein Offline-Demo-Scout ist enthalten. |
| Portalimport | Übernimmt einzelne, vom Benutzer eingefügte Anzeigen von Indeed, StepStone, LinkedIn, XING oder anderen Quellen. Es gibt bewusst keinen automatisierten Portal-Login oder Scraper. |
| Matcher | Bewertet Muss-/Kann-Skills, Sprache, Ort, Arbeitsart, Gehalt und Ausschlussfirmen. Alias-, Ähnlichkeits- und optionale LLM-Stufe liefern nachvollziehbare Komponenten und Provenienz. |
| Writer | Erstellt ein deutsches Anschreiben ausschließlich aus belegten Profildaten. Interne Scores/Risiken gelangen nicht ins Anschreiben; unsichere LLM-Ausgaben fallen auf eine Vorlage zurück. |
| Tracker | Persistiert Jobs, Matches, Entwürfe, Status und unveränderliche Historien. Follow-ups, Inbox-Sync und Versand sind dry-run-first und idempotent. |
| Auswertung | Funnel, Antwortzeiten, Score-Bänder, CV-Check, Interviewleitfaden, Markdown-Report und Unicode-PDF/ZIP-Export. |
| Web | Login, CSRF-Schutz, Aktionslimits, isolierte Benutzerdaten, sichere Header, Passwortwechsel und vollständige Account-Löschung. |

Die zentralen Designentscheidungen stehen in [ARCHITECTURE.md](ARCHITECTURE.md),
die Daten- und Git-Grenze in [DATA_CONTRACT.md](DATA_CONTRACT.md).

## Schnellstart mit Docker

Voraussetzungen: Git und Docker Desktop. In PowerShell:

```powershell
git clone https://github.com/abdelbasetab/job-application-agent.git
cd job-application-agent
Copy-Item .env.example .env
notepad .env
```

Für die einmalige lokale Einrichtung diese Werte in `.env` setzen:

```dotenv
WEB_ALLOW_REGISTRATION=true
WEB_SECURE_COOKIES=false
EMAIL_DRY_RUN=true
EMAIL_SYNC_DRY_RUN=true
```

Danach starten:

```powershell
docker compose up --build -d --force-recreate
docker compose ps
docker compose logs --tail 50 web
```

`http://127.0.0.1:7860` öffnen, das erste Konto registrieren und danach
`WEB_ALLOW_REGISTRATION=false` setzen. Mit
`docker compose up -d --force-recreate` wird die geschlossene Registrierung
aktiv; das Konto bleibt im Volume erhalten. `docker compose down` stoppt die
App, ohne Daten zu löschen. **Nicht** `docker compose down -v` verwenden, wenn
die gespeicherten Daten erhalten bleiben sollen.

## Entwicklungs- und CLI-Schnellstart

Voraussetzung: Python 3.11 oder 3.12.

```bash
git clone https://github.com/abdelbasetab/job-application-agent.git
cd job-application-agent
cp .env.example .env

# Reproduzierbare Entwicklungsumgebung
uv sync --locked --extra dev

# Vollständig offline und ohne Zugangsdaten
uv run job-agent run-pipeline --demo --reset-demo-db --limit 5
uv run job-agent show-applications --demo
uv run job-agent eval
```

Ohne `uv` ist eine normale Installation möglich:

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
python -m pytest
```

Das synthetische Beispiel [sample_cv.txt](docs/examples/sample_cv.txt) enthält
keine personenbezogenen Echtdaten.

## Weboberfläche ohne Docker starten

Die sichere Voreinstellung deaktiviert offene Registrierung. Für den ersten
Start entweder in `.env` ein einmaliges Bootstrap-Konto setzen:

```dotenv
WEB_BOOTSTRAP_EMAIL=admin@example.invalid
WEB_BOOTSTRAP_PASSWORD=<langes-zufälliges-passwort>
WEB_ALLOW_REGISTRATION=false
WEB_SECURE_COOKIES=false
```

Dann:

```bash
uv run job-agent doctor
uv run job-agent web --host 127.0.0.1 --port 7860
```

`http://127.0.0.1:7860` öffnen und das Bootstrap-Passwort nach dem ersten Login
unter **Einstellungen → Account-Sicherheit** ändern. `WEB_SECURE_COOKIES=false`
ist nur für lokales HTTP gedacht; bei HTTPS muss der Wert `true` sein.

Alternativ kann für eine kontrollierte lokale Einrichtungsphase
`WEB_ALLOW_REGISTRATION=true` gesetzt und danach wieder deaktiviert werden.

## Eigenen Lebenslauf verwenden

Der Offline-Demoablauf verwendet nur die synthetische Demo-Identität. Für ein
eigenes Profil wird ein LLM-Provider benötigt:

```dotenv
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:7b-instruct
LLM_BASE_URL=http://127.0.0.1:11434
ENABLE_LLM_AGENTS=false
```

```bash
uv run job-agent read-cv --cv /pfad/lebenslauf.pdf --out data/profile/profile.yaml
uv run job-agent run-pipeline --profile data/profile/profile.yaml --demo --reset-demo-db
```

Für OpenAI-kompatible Gateways werden `LLM_PROVIDER=openai` oder
`LLM_PROVIDER=kiconnect`, `LLM_BASE_URL` und `OPENAI_API_KEY` gesetzt. Anthropic
und Groq werden ebenfalls unterstützt. `ENABLE_LLM_AGENTS=true` aktiviert den
optionalen Matcher/Writer-Pfad; bei Fehlern bleibt der deterministische Fallback
verfügbar. Persistenter Profilkontext wird mit `ENABLE_PROFILE_MEMORY=true` und
optional `EMBEDDING_MODEL=<modell>` aktiviert. Der kleine Vektorindex liegt als
SQLite-Datei je Benutzer im Datenverzeichnis; `ENABLE_CHROMA` bleibt nur als
Kompatibilitätsalias für ältere Konfigurationen erhalten.

## Live-Jobs und Portalimport

Adzuna benötigt `ADZUNA_APP_ID` und `ADZUNA_APP_KEY`. Die BA-Jobsuche verwendet
den dokumentierten festen `X-API-Key`. Externe APIs können ausfallen oder ihre
Antwortstruktur ändern; ungültige Antworten werden als leeres Ergebnis behandelt.

```bash
uv run job-agent run-pipeline --profile data/profile/profile.yaml --query "Werkstudent Python" --limit 10
uv run job-agent run-pipeline --profile data/profile/profile.yaml --direct --query "Data Engineer" --limit 10
```

Ohne `--cv`/`--profile` wird nur ein bereits in derselben Datenbank persistiertes
Profil wiederverwendet. Das synthetische Profil wird ausschließlich mit `--demo`
aktiviert.

Indeed, StepStone und LinkedIn bieten für diesen persönlichen Jobsuch-Use-Case
keine allgemein verfügbare API, über die das Projekt Konten verbinden und
Suchergebnisse dauerhaft übernehmen dürfte. Automatisierte Portal-Logins,
CAPTCHA-Umgehung, Scraping und Auto-Apply sind deshalb bewusst nicht enthalten.
Der offizielle Indeed-MCP befindet sich in Beta und ist laut Dokumentation nur
als Claude-Connector verfügbar; LinkedIn- und StepStone-Schnittstellen richten
sich primär an genehmigte Recruiting-/ATS-Partner. Stand: 21. Juli 2026.

- [Indeed MCP](https://docs.indeed.com/mcp/)
- [LinkedIn API-Zugang](https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access)
- [LinkedIn-Nutzungsbedingungen](https://www.linkedin.com/legal/user-agreement)
- [StepStone-Nutzungsbedingungen](https://www.stepstone.de/Ueber-StepStone/legal-notes/general-terms-use/)

Für eine einzelne gefundene Stelle steht in der Weboberfläche die
**Portal- & URL-Inbox** bereit:

1. Link der Stellenanzeige einfügen.
2. Jobtitel, Unternehmen, Standort und den sichtbaren Anzeigentext übernehmen.
3. **Bewerten** anklicken.

Der Link wird ausschließlich gespeichert und zur Quellenkennung verwendet; die
App ruft das Portal nicht automatisch ab. Der eingefügte Text läuft danach durch
denselben Matcher-, Writer- und Trackerpfad wie API-Stellen. Indeed, StepStone,
LinkedIn und XING werden anhand der URL als Quelle gekennzeichnet.

## E-Mail und Inbox

Webkonten speichern eigene SMTP/IMAP- oder OAuth-Zugangsdaten. Sie erben niemals
die Prozess-Zugangsdaten des Betreibers. Neue Konten starten mit:

- Versand als Dry-run,
- Inbox-Sync nur als Vorschlag,
- automatischem Echtversand aus.

Die Richtlinien werden in **Einstellungen** pro Konto geändert. Echter Versand
verlangt zusätzlich direkt vor dem Senden eine UI-Bestätigung. Gleiche
Versandanforderungen werden durch einen persistierten Outbox-Schlüssel nur einmal
verarbeitet. Inbox-Nachrichten werden per IMAP UID/Message-ID dedupliziert und
ältere Antworten können einen fortgeschrittenen Status nicht zurückstufen.
SMTP-Zugangsdaten werden ausschließlich über TLS verwendet: Port 465 nutzt
implizites TLS, andere Ports STARTTLS; unverschlüsseltes SMTP wird abgelehnt.

Die `.env`-Mailwerte gelten nur für lokale CLI-Nutzung. OAuth benötigt eine
explizite externe Basis-URL, zum Beispiel:

```dotenv
EMAIL_OAUTH_REDIRECT_BASE=https://jobs.example.org
EMAIL_OAUTH_GOOGLE_CLIENT_ID=
EMAIL_OAUTH_GOOGLE_CLIENT_SECRET=
```

## Häufige Befehle

```bash
uv run job-agent --help
uv run job-agent doctor
uv run job-agent review-cv --cv docs/examples/sample_cv.txt
uv run job-agent evaluate-jd --file stellenanzeige.txt --title "Werkstudent KI" --demo
uv run job-agent follow-ups --demo
uv run job-agent patterns --demo
uv run job-agent interview-prep --job-id <job-id> --demo
uv run job-agent eval
```

## Docker und Deployment

Das Image wird mehrstufig gebaut, läuft als UID 10001 ohne Linux-Capabilities
und schreibt nur nach `/data` sowie in das temporäre `/tmp`. Compose bindet den
Port standardmäßig ausschließlich an `127.0.0.1`.

```bash
cp .env.production.example .env
# Bootstrap-Zugang und benötigte Secrets außerhalb von Git setzen
docker compose up --build -d
docker compose ps
```

Für einen öffentlichen Betrieb sind HTTPS-Reverse-Proxy,
`WEB_SECURE_COOKIES=true`, persistentes `/data`, Backups und eine feste externe
OAuth-URL Pflicht. Die vollständige Anleitung steht in
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md), Backup/Upgrade/Fehlerbehebung in
[docs/OPERATIONS.md](docs/OPERATIONS.md).

## Qualitätssicherung

```bash
uv run ruff check src tests
uv run mypy src
uv run pytest --cov=job_agent --cov-fail-under=60
uv run python -m job_agent.main eval --json-out eval_report.json
uvx --from pip-audit==2.10.1 pip-audit --requirement requirements-runtime.lock --disable-pip
node --check src/job_agent/web_static/app.js
```

Tests mit echten Diensten sind separat markiert:

```bash
uv run pytest -m integration
```

GitHub Actions führt Lint, strikte Typprüfung, Offline-Tests, Evaluation,
Dependency-Audit und Docker-Build unter Python 3.11 und 3.12 aus. `uv.lock`
sperrt die vollständige Auflösung; `requirements-runtime.lock` ist der daraus
exportierte Container-Satz.

## Repository-Struktur

```text
src/job_agent/
  agents/          Profiler, Scout, Matcher, Writer, Tracker, CV/Interview
  memory/          migrierte SQLite-Stores und lokaler Profil-Vektorindex
  schemas/         Pydantic-Verträge
  tools/           Jobsuche, manueller Portalimport, E-Mail, Reports, Export, Liveness
  utils/           Konfiguration, CV- und Netzwerkvalidierung, LLM, Doctor
  web.py           stdlib-Webserver und API
  web_static/      HTML/CSS/JavaScript-Client
tests/             Offline-Tests; externe Tests tragen den Marker integration
docs/              Deployment, Betrieb und synthetische Beispiele
data/              ausschließlich lokale Laufzeitdaten, weitgehend gitignoriert
```

## Grenzen und Verantwortung

- Externe Stellenanzeigen, Klassifikationen und LLM-Texte können falsch sein.
- Geschützte Stellenportale werden nicht automatisch durchsucht oder bedient.
- Die E-Mail-Klassifikation ist regelbasiert und ersetzt keine manuelle Prüfung.
- Der In-Prozess-Autopilot ist kein hochverfügbarer Scheduler und endet beim Neustart.
- Zugangsdaten werden lokal geschützt, aber ein kompromittierter Host bleibt ein Risiko.
- Das Projekt bietet keine Rechts-, Datenschutz- oder Karriereberatung.

Sicherheitsdetails und bekannte Restrisiken: [SECURITY.md](SECURITY.md).
Datenschutzhinweise: [PRIVACY.md](PRIVACY.md). Lizenz: [MIT](LICENSE).
