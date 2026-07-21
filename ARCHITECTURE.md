# Architektur

## Ziel und Systemgrenze

Der Job Application Agent ist eine lokal betreibbare Einzelinstanz für mehrere
Benutzer. Er sammelt Stellen, bewertet sie gegen ein Kandidatenprofil, erzeugt
prüfbare Entwürfe und verwaltet den Bewerbungsstatus. Er ist weder ein
vollautomatisches Bewerbungsportal noch ein verteiltes SaaS-System.

```text
Browser / CLI
      │
      ▼
Web-API / Typer-Kommandos
      │
      ▼
Pipeline ── Profiler ── Scout ── Matcher ── Writer ── Tracker
      │          │          │         │          │
      │          └──── externe LLMs / Job-APIs (optional) ────┘
      ▼
pro Benutzer: SQLite + Credential-Store + Profil-Vektorindex + Exporte
```

Alle Agentenübergaben verwenden Pydantic-Modelle. Freitext von Stellenbörsen,
Lebensläufen und LLMs gilt immer als nicht vertrauenswürdig.

## Komponenten

- `pipeline.py` orchestriert den Ablauf und persistiert Profil, Jobs, Matches,
  Entwürfe und Trackerstatus.
- `agents/` enthält Profiler, Scout, Matcher, Writer, Tracker, CV-Reviewer und
  Interviewvorbereitung.
- `tools/` kapselt externe Job-APIs, benutzergesteuerten Text-/URL-Import,
  SMTP/IMAP/OAuth, Liveness, Reports und Exporte.
- `memory/store.py` ist die fachliche SQLite-Datenbank. Migrationen sind
  append-only und über `PRAGMA user_version` versioniert.
- `memory/auth_store.py` enthält Benutzer und gehashte Sessions.
- `memory/credential_store.py` speichert Integrationsgeheimnisse per
  AES-256-GCM; Schlüssel und Ciphertext liegen getrennt, aber auf demselben Host.
- `memory/profile_index.py` verwaltet einen kleinen profilbezogenen
  SQLite-Vektorindex. Embedding-Konfigurationen sind gefingert, veraltete
  Dokument-IDs werden vor einem Re-Index entfernt und die wenigen Snippets
  werden exakt per Cosinus-Ähnlichkeit durchsucht.
- `web.py` ist ein `ThreadingHTTPServer` mit Authentifizierung, CSRF,
  Größenlimits, Aktionslimits und statischen Assets.

## Datenfluss

1. Ein Profil wird explizit aus einem CV oder dem synthetischen Demo-Profil
   erstellt und in der aktiven Profilschleife gespeichert.
2. Scout fragt reale Anbieter oder den Demo-Adapter deterministisch ab.
   HTTP-/JSON-Fehler führen zu leeren Quellenergebnissen. Generative Ausgaben
   dürfen keine Job-Quelldatensätze erzeugen oder verändern.
   Einzelne Anzeigen geschützter Portale gelangen ausschließlich als vom
   Benutzer eingefügter Link und Text in den Ablauf; es gibt keinen
   automatisierten Portal-Login, Crawler oder Auto-Apply-Pfad.
3. Matcher berechnet eine deterministische Bewertung. Eine optionale
   LLM-Bewertung muss Job-ID, Mengenbeziehungen, Gates und Scorekonsistenz
   erfüllen; andernfalls gilt der deterministische Wert.
4. Writer erhält nur belegte Profilfakten und verifizierte Jobfakten. Der
   Originaltext wird als untrusted data begrenzt. Qualitätschecks entscheiden
   zwischen akzeptierter LLM-Ausgabe und sicherer Vorlage.
5. Tracker schreibt aktuellen Zustand und unveränderliche Historien. Versand
   reserviert vor SMTP atomar einen Outbox-Schlüssel.

## Mandantentrennung

Der globale Auth-Store liegt unter `JOB_AGENT_DATA_DIR/auth.db`. Fachliche Daten
liegen ausschließlich unter:

```text
data/users/<numerische-user-id>/
  job_agent.db / demo_job_agent.db
  credentials.db
  credentials.key
  profile_index/profile_vectors.sqlite3
  output/<job-id>/
  cv_source.*
```

Vom Client übergebene DB-Pfade werden auf einen Dateinamen reduziert und in das
Verzeichnis des angemeldeten Benutzers rebasiert. Ein Webbenutzer ohne eigenes
E-Mail-Konto erhält niemals Betreiber-Zugangsdaten aus `.env`.

## Persistenz und Historie

Die aktuelle Store-Version enthält unter anderem:

- aktuelle und historische Jobs,
- aktuelle und historische Anschreiben,
- aktuellen Status plus append-only `status_events`,
- versionierte Profile und aktives Profil,
- aktuelle Matches plus `match_history`,
- Liveness-Ergebnisse,
- E-Mail-Audit, verarbeitete Inbox-Nachrichten und Outbox-Reservierungen.

SQLite läuft mit WAL. Mehrere Threads innerhalb einer Instanz sind vorgesehen;
mehrere Container-Replikate auf derselben DB sind es nicht.

## Parallelität

- Pro Benutzer darf nur eine Pipeline gleichzeitig laufen.
- Global begrenzt ein Semaphore die Zahl paralleler Pipelines.
- Fortschrittseinträge sind begrenzt und abgeschlossene Einträge werden
  entfernt.
- Der E-Mail-Autopilot besitzt einen globalen Nichtüberlappungs-Lock.
- Session- und Rate-Limit-Caches sind begrenzt.

Der Autopilot lebt nur im Prozess. Für hochverfügbare oder verteilte Planung
wäre ein externer Scheduler mit Queue und transaktionaler Worker-Zustellung nötig.

## Vertrauensgrenzen

- Netzwerkziele für Scraper, Liveness, SMTP und IMAP werden auf öffentliche
  Adressen geprüft; Redirects werden erneut validiert. Private Ziele sind nur
  durch eine bewusste Betreiberoption erlaubt.
- CV-Dateien werden nach Größe, Endung und Magic/Containerstruktur validiert.
- Download- und Exportpfade bleiben in einem festen Benutzerverzeichnis.
- Browserausgaben werden escaped; eine Content-Security-Policy verbietet
  fremde Skripte und Frames.
- LLM-Provenienz (`deterministic`/`template` oder `llm` plus Modell) wird in
  Schema und Report gespeichert.

## Bewusste Grenzen

- SQLite und der In-Prozess-Scheduler bedeuten: eine aktive Serverinstanz.
- Die lokale Schlüsseldatei ist kein KMS; Host- oder Volume-Kompromittierung
  kompromittiert auch die Credentials.
- Stellenbörsen und Mailanbieter sind externe, veränderliche Abhängigkeiten.
- Automatische Live-Suche ist auf dokumentiert angebundene Quellen beschränkt;
  Indeed, StepStone, LinkedIn und XING nutzen nur den manuellen Einzelimport.
- Regeln und LLMs können Fehlentscheidungen treffen. Der Mensch bleibt die
  Freigabestelle für Empfänger, Anschreiben und Status.
