# Deployment

## Zielbild

Das unterstützte Produktionsziel ist **eine** Containerinstanz hinter einem
HTTPS-Reverse-Proxy mit einem persistenten, nur für diese Instanz beschreibbaren
`/data`-Volume. Mehrere Replikate teilen weder SQLite noch den In-Prozess-
Autopilot sicher.

## 1. Konfiguration

```bash
cp .env.production.example .env
```

Geheimnisse bevorzugt direkt im Secret Manager der Plattform setzen. Für den
ersten Start sind bei deaktivierter Registrierung zwingend erforderlich:

```dotenv
WEB_BOOTSTRAP_EMAIL=admin@example.org
WEB_BOOTSTRAP_PASSWORD=<mindestens-12-zeichen-zufällig>
WEB_ALLOW_REGISTRATION=false
WEB_SECURE_COOKIES=true
JOB_AGENT_DATA_DIR=/data
```

Das Bootstrap-Konto wird nur erzeugt, wenn noch kein Benutzer existiert. Das
Passwort danach in der UI ändern und den Bootstrap-Wert aus der Laufzeitumgebung
entfernen.

OAuth benötigt die exakt extern sichtbare HTTPS-Basis ohne Pfad:

```dotenv
EMAIL_OAUTH_REDIRECT_BASE=https://jobs.example.org
```

## 2. Lokal gebundenes Compose

```bash
docker compose config
docker compose up --build -d
docker compose ps
docker compose logs --tail 100 web
```

Compose bindet ohne Änderung an `127.0.0.1:7860`. Für lokalen HTTP-Test muss
`WEB_SECURE_COOKIES=false` gelten. Nicht einfach `BIND_ADDRESS=0.0.0.0` setzen,
ohne davor TLS und Zugriffsschutz bereitzustellen.

## 3. Reverse Proxy

Beispiel für Nginx; Zertifikatsverwaltung ist deploymentspezifisch:

```nginx
server {
    listen 443 ssl http2;
    server_name jobs.example.org;

    client_max_body_size 12m;
    proxy_connect_timeout 10s;
    proxy_read_timeout 180s;

    location / {
        proxy_pass http://127.0.0.1:7860;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

Die App konstruiert OAuth-Redirects nicht aus dem `Host`-Header, sondern nur
aus `EMAIL_OAUTH_REDIRECT_BASE`.

## 4. Git-basierte Containerplattform

Für Render, Railway, Fly.io oder vergleichbare Dienste:

- Repository über den `Dockerfile` bauen, Target `runtime`;
- Containerport `7860` veröffentlichen;
- persistentes Volume nach `/data` mounten;
- Healthcheck `GET /api/auth/me` verwenden;
- alle Secrets in der Plattform hinterlegen;
- genau eine Replik und Rolling-Update ohne Parallelbetrieb konfigurieren;
- `WEB_SECURE_COOKIES=true` und öffentliche Registrierung aus lassen.

Eine Plattform ohne persistentes Dateisystem ist ungeeignet: Accounts,
Profile, Status und Schlüssel würden bei jedem Deployment verschwinden.

## 5. Vor Freigabe

```bash
uv sync --locked --extra dev
uv run ruff check src tests
uv run mypy src
uv run pytest
uv run python -m job_agent.main eval
docker build --target runtime -t job-agent:release .
```

Danach manuell prüfen:

- HTTPS und Secure-Cookie funktionieren,
- Registrierung ist geschlossen,
- Login/Passwortwechsel funktionieren,
- `/data` bleibt nach Neustart erhalten,
- Dry-run ist für neue Mailkonten aktiv,
- Backup und Wiederherstellung wurden getestet.

## 6. Release in Git

```bash
git status --short
git diff --check
git add .
git commit -m "Harden application and production deployment"
git push origin main
```

Vor `git add .` die Dateiliste prüfen. `.env`, CVs, Datenbanken, Schlüssel und
Exports dürfen nicht erscheinen. Commit/Push werden bewusst nicht von der App
automatisiert.
