# Betriebshandbuch

## Zustandsmodell

Der gesamte dauerhafte Zustand liegt in `/data` beziehungsweise
`JOB_AGENT_DATA_DIR`. Dazu gehören Auth-DB, Benutzer-DBs, Credential-Key,
Profil-Vektorindex und Exporte. Code und Image sind ersetzbar; `/data` ist es
nicht.

## Health und Logs

```bash
docker compose ps
docker compose logs --tail 200 web
curl --fail http://127.0.0.1:7860/api/auth/me
```

Der Health-Endpunkt bestätigt nur Prozess/HTTP-Liveness, nicht die Erreichbarkeit
von LLM, Jobbörsen oder Mailserver. Dafür `job-agent doctor` und die
Verbindungstests in den Einstellungen verwenden.

## Backup

Für ein einfaches konsistentes Volume-Backup die einzelne Instanz kurz stoppen:

1. `docker compose stop web`
2. das vollständige `/data`-Volume inklusive `.db`, `-wal`, `-shm` und
   `credentials.key` in ein verschlüsseltes Backup kopieren,
3. Prüfsumme und Lesbarkeit kontrollieren,
4. `docker compose start web`.

DB und Credential-Key müssen gemeinsam gesichert werden. Ohne Key sind
gespeicherte E-Mail-/OAuth-Secrets nicht wiederherstellbar. Backups enthalten
personenbezogene Daten und brauchen dieselben oder strengere Schutzmaßnahmen.

## Upgrade

1. Release-Notes und Dependency-Diff prüfen.
2. Konsistentes Backup erstellen.
3. Neues Image mit unverändertem `/data` starten.
4. Login, Statushistorie, Export und Dry-run testen.
5. Logs auf Migrations- oder Entschlüsselungsfehler prüfen.

Migrationen laufen beim Öffnen einer DB automatisch und nur vorwärts.

## Rollback

Ein Code-Rollback allein ist nach einer DB-Migration nicht garantiert. Die
sichere Variante ist: Container stoppen, neues Datenvolume archivieren, Code
und das gemeinsam vor dem Upgrade erstellte Backup zurücksetzen und danach
erneut testen.

## Credential-Key-Verlust

Ist `credentials.key` verloren oder beschädigt, darf kein neuer Schlüssel über
die alte DB gelegt werden. Gespeicherte Integrationen sind dann nicht
entschlüsselbar. Lokale Credential-DB und Key kontrolliert archivieren,
Integrationen in der UI entfernen/neu verbinden und Anbieter-Tokens widerrufen.

## Incident-Ablauf

1. Exposition begrenzen: Instanz vom Netz nehmen oder echten Mailversand stoppen.
2. API-, OAuth-, SMTP-/IMAP- und Bootstrap-Secrets widerrufen/rotieren.
3. Logs, Image-Digest, Git-Commit und betroffene Daten sichern.
4. Umfang und betroffene Benutzer bestimmen.
5. Rechtliche/vertragliche Meldepflichten prüfen.
6. Aus sauberem Image und geprüftem Backup wiederherstellen.

## Kapazität und Grenzen

- Einzelinstanz, keine gemeinsame SQLite-Nutzung über Replikate.
- Maximal vier parallele Pipelines, höchstens eine pro Benutzer.
- CV-Upload und JSON-Request sind größenbegrenzt.
- Profilindex und Exporte wachsen ohne automatische Retention.
- Autopilot-Zeitpläne gehen bei Neustart verloren und müssen neu gestartet werden.

Speicherverbrauch, Datenalter und Volume-Auslastung daher extern überwachen.
