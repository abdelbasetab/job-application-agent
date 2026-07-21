# Datenvertrag und Git-Grenze

Dieses Dokument trennt versionierbaren Projektinhalt von personenbezogenen
Laufzeitdaten. Es ist zugleich die Checkliste vor jedem Git-Push.

## Darf in Git

- Quellcode unter `src/`, Tests und synthetische Fixtures,
- Prompts und das synthetische Demo-Profil,
- `data/profile/profile.yaml.example`, niemals `profile.yaml`,
- Dokumentation, Docker-/CI-Dateien,
- `.env.example` und `.env.production.example` ohne verwendbare Secrets,
- `uv.lock` und der daraus erzeugte `requirements-runtime.lock`.

## Darf nicht in Git

- `.env` und alle echten API-, OAuth-, SMTP- oder IMAP-Geheimnisse,
- CVs, Profil-YAMLs, Stellen-Snapshots und Anschreiben realer Personen,
- SQLite-, WAL-, Profilindex- und Credential-Dateien,
- Exporte, Logs, Testartefakte und lokale Tool-Berechtigungen,
- private Schlüssel oder Zertifikatsschlüssel.

`.gitignore` bildet diese Grenze ab. Vor einem Push ist trotzdem
`git status --short` zu prüfen; Git ignoriert Dateien nicht rückwirkend, wenn
sie bereits getrackt wurden.

## Fachliche Verträge

Die kanonischen Modelle liegen unter `src/job_agent/schemas/`:

- `UserProfile`: Identität, belegte Skills, Erfahrung, Ausbildung, Sprachen und
  Präferenzen.
- `JobPosting`: Quell-ID, URL, Fakten, Muss-/Kann-Anforderungen, Gehalt und
  Arbeitsform.
- `MatchResult`: Score, belegte Treffer/Lücken, Rubrik, Risiko, Empfehlung und
  Bewertungsprovenienz.
- `GeneratedApplication`: Anschreiben, Qualitätschecks und
  Erzeugungsprovenienz.
- `ApplicationStatus`: aktueller Trackerzustand, Zeitpunkte und Notizen.

Pydantic verbietet bei sicherheitskritischen Ergebnisverträgen zusätzliche
Felder. LLM-Antworten werden nicht direkt in die Datenbank übernommen, sondern
zuerst validiert und fachlich gegengeprüft.

## Historienregeln

- `jobs`, `applications`, `matches` und `status` enthalten den aktuellen Stand.
- Die zugehörigen History-/Eventtabellen sind append-only.
- Ein E-Mail-Inbox-Ereignis wird anhand UID/Message-ID/Fingerprint nur einmal
  verarbeitet.
- Automatische Mailübergänge sind monoton; eine ältere Eingangsbestätigung darf
  beispielsweise kein Interview zurückstufen.
- Eine Outbox-Reservierung wird vor der SMTP-Verbindung geschrieben. Ein
  identischer Schlüssel darf nicht erneut zugestellt werden.

## Aufbewahrung, Export und Löschung

Es gibt keine automatische Aufbewahrungsfrist. Betreiber müssen eine zur
eigenen Rechtsgrundlage passende Frist festlegen und Backups einbeziehen.

Die Account-Löschung entfernt Benutzerzeile, Sessions und das zugehörige
`data/users/<id>`-Verzeichnis. Externe Backups, bereits versandte E-Mails und
Daten bei LLM-/Mail-/Job-Anbietern werden dadurch nicht gelöscht.

Exports dürfen nur unter dem Benutzerverzeichnis entstehen. Zulässige
Downloads sind auf PDF, JSON, ZIP und Markdown begrenzt.

## Migration und Kompatibilität

SQLite-Migrationen werden ausschließlich angehängt. Ein Downgrade des Codes
garantiert keine Rückwärtskompatibilität mit einer neueren DB. Deshalb gilt:

1. konsistentes Backup vor Upgrade,
2. neue Version zunächst gegen eine Backup-Kopie prüfen,
3. bei Rollback Code **und** Datenbank gemeinsam zurücksetzen.

Der Credential-Store liest das alte authentifizierte Format einmalig und
schreibt es nach erfolgreicher Entschlüsselung als AES-GCM `v2` zurück.
