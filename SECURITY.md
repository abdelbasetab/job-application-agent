# Sicherheitsrichtlinie

## Unterstützte Version

Sicherheitskorrekturen werden auf dem aktuellen `main`-Stand gepflegt. Für eine
Deployment-Version sollte ein eigener Git-Tag verwendet werden.

## Schwachstellen melden

Bitte keine ausnutzbaren Details, Zugangsdaten oder personenbezogenen Daten in
ein öffentliches Issue schreiben. Verwende, falls das Repository auf GitHub
liegt, **Security → Report a vulnerability** (Private Vulnerability Reporting)
oder kontaktiere den Repository-Eigentümer über einen privaten Kanal.

Eine Meldung sollte Version/Commit, Auswirkung, reproduzierbare Minimal-Schritte
und vorgeschlagene Abhilfe enthalten. Niemals echte CVs oder Tokens beilegen.

## Schutzmaßnahmen

- Passwörter: PBKDF2-HMAC-SHA256 mit zufälligem Salt und 240.000 Iterationen,
  mindestens 12 und höchstens 256 Zeichen.
- Sessions: zufällige Tokens; in SQLite liegt nur SHA-256, Ablauf nach sieben
  Tagen, `HttpOnly`, `SameSite=Lax`, unter HTTPS zusätzlich `Secure`.
- CSRF: Double-Submit-Cookie und `X-CSRF-Token` für Zustandsänderungen.
- Missbrauchsschutz: Login-/Registrierungs- und Aktionslimits, begrenzte
  In-Memory-Caches, Pipeline-Semaphore und Größenlimits.
- Mandantentrennung: serverseitige Pfadkonfinierung je numerischer User-ID.
- Secrets: E-Mail-/OAuth-Payloads per AES-256-GCM mit zufälligem Nonce und
  Integritätsprüfung; Schlüsseldatei mit best-effort Modus `0600`.
- Netzwerk: Ablehnung von Loopback, privaten, Link-local, reservierten und
  nicht auflösbaren Hosts; erneute Prüfung jedes HTTP-Redirects.
- E-Mail: Dry-run-Voreinstellung, explizite Echtversandbestätigung, persistente
  Outbox-Idempotenz, verpflichtendes SMTP-TLS/IMAPS mit Zertifikatsprüfung,
  read-only/peek IMAP und monotone Statusübergänge.
- LLM: typisierte Antworten, Job-ID-Bindung, Evidenz-/Mengenprüfungen,
  Prompt-Injection-Grenzen und sichere deterministische Fallbacks.
- Stellenportale: kein automatisierter Login, kein Credential-/Cookie-Import,
  kein CAPTCHA-Bypass, kein Scraping und kein Auto-Apply. Manuelle Portaltexte
  bleiben nicht vertrauenswürdige Eingaben und werden größenbegrenzt validiert.
- Browser: CSP, Frame-Verbot, `nosniff`, Referrer-/Permissions-Policy und
  kontextgerechtes Escaping.
- Container: Non-Root, read-only Root-Dateisystem, keine Capabilities,
  `no-new-privileges`, begrenztes temporäres Dateisystem.
- Supply Chain: gelockte Runtime-Hashes, gepinnter Basisimage-Digest und ein
  `pip-audit`-Gate in CI.

## Produktionsanforderungen

- Nur hinter HTTPS betreiben und `WEB_SECURE_COOKIES=true` setzen.
- Öffentliche Registrierung deaktiviert lassen; Bootstrap-Secrets über einen
  Secret Manager, nicht über Git, bereitstellen.
- Nur eine App-Replik betreiben, solange SQLite und In-Prozess-Scheduler genutzt
  werden.
- `/data` verschlüsselt und zugriffsbeschränkt persistieren und regelmäßig
  sichern.
- Ausgehenden Netzwerkverkehr nach Möglichkeit auf benötigte Anbieter begrenzen.
- Reverse Proxy mit Request-/Timeout-Limits einsetzen und Sicherheitsupdates
  des Basisimages sowie der gesperrten Abhängigkeiten regelmäßig einspielen.

## Restrisiken

- Schlüsseldatei und Ciphertext liegen auf demselben Volume. Wer Host oder
  Volume vollständig lesen kann, kann auch gespeicherte Provider-Secrets lesen.
  Für SaaS ist ein KMS/HSM erforderlich.
- DNS kann sich zwischen Validierung und Verbindungsaufbau ändern. Egress-Regeln
  und ein kontrollierter Proxy bleiben die stärkere SSRF-Grenze.
- PBKDF2 schützt keine schwachen oder wiederverwendeten Benutzerpasswörter.
- Externe Job-, LLM-, OAuth- und Mailanbieter sehen die an sie gesendeten Daten
  gemäß ihrer eigenen Bedingungen.
- Nutzungsbedingungen externer Stellenportale können sich ändern. Betreiber
  müssen vor einer neuen API-Anbindung Berechtigung und Zweckbindung prüfen.
- Regelbasierte Mailklassifikation und LLM-Inhalte können falsch sein.
- Der stdlib-Webserver ist für eine einzelne, moderat belastete Instanz gedacht,
  nicht als direkt exponierter Edge-Server.

## Betreiber-Check vor Veröffentlichung

```bash
git status --short
uv run ruff check src tests
uv run mypy src
uv run pytest
uv run job-agent doctor
docker compose config --quiet
```

Zusätzlich sollte ein Secret-Scanner in der Hosting-Plattform aktiviert werden.
