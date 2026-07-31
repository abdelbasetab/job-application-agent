# Datenschutzhinweise für Betreiber

Dieses Projekt ist Software, kein fertiger Auftragsverarbeitungsvertrag und
keine Rechtsberatung. Wer die Anwendung bereitstellt, ist für Rechtsgrundlage,
Informationspflichten, Löschfristen und Verträge mit Drittanbietern
verantwortlich.

## Verarbeitete Daten

Je nach Nutzung können folgende personenbezogene Daten entstehen:

- Login-E-Mail und Passwort-Hash,
- Lebenslauftext, Kontaktangaben, Ausbildung, Erfahrung, Skills und Präferenzen,
- Stellenanzeigen, Bewertungen, Anschreiben und Bewerbungsstatus,
- Empfängeradressen, Mail-Metadaten, klassifizierte Antwortausschnitte und
  Versand-Auditdaten,
- OAuth-/SMTP-/IMAP-Zugangsdaten in verschlüsselter lokaler Form,
- technische Logs, Zeitpunkte und IP-basierte temporäre Rate-Limit-Schlüssel.

## Speicherorte

Laufzeitdaten liegen unter `JOB_AGENT_DATA_DIR`, im Container standardmäßig
`/data`. Benutzerdaten sind nach numerischer User-ID getrennt. Exporte und
Backups sind zusätzliche Kopien und müssen separat geschützt werden.

Rate-Limit- und Pipeline-Fortschrittsdaten leben begrenzt im Arbeitsspeicher
und verschwinden beim Neustart.

## Optionale Empfänger außerhalb der Instanz

- konfigurierter LLM-/Embedding-Anbieter: CV- oder Jobfakten und Prompts,
- Adzuna und BA-Jobsuche: Suchbegriffe und technische Requestdaten,
- SMTP-/IMAP-/OAuth-Anbieter: E-Mail-Inhalte und Kontometadaten. Empfänger ist
  dabei stets die selbst konfigurierte Kontroll-E-Mail-Adresse des Betreibers,
  nie ein Arbeitgeber,
- öffentliche Zielseiten bei optionaler Detailanreicherung oder Liveness-Prüfung:
  IP-Adresse und Request-Metadaten.

Der Offline-Demomodus benötigt diese Übermittlungen nicht. Betreiber sollten
je Anbieter Datenstandort, Aufbewahrung, Trainingseinstellungen und
Vertragsgrundlage prüfen und nur die notwendigen Funktionen aktivieren.

## Datenminimierung

- Nur ein synthetisches Demo-Profil wird mit Git ausgeliefert.
- LLM-Writer erhält keine internen Risiko- oder Begründungstexte.
- Inbox-Sync verarbeitet nur eine begrenzte Anzahl, bevorzugt Textteile und
  überspringt Anhänge.
- E-Mail-Zugangsdaten werden nicht an Browserantworten zurückgegeben.
- Logs sollten keine Secrets oder vollständigen Mail-/CV-Inhalte enthalten.

## Löschung und Auskunft

Die UI-Funktion **Account und Daten löschen** entfernt Login, Sessions und das
lokale Benutzerverzeichnis nach Passwort- und `DELETE`-Bestätigung. Nicht
erfasst sind:

- Betreiber-Backups,
- bereits versandte oder beim Mailanbieter gespeicherte Nachrichten,
- Daten, die zuvor an externe LLM-/Jobanbieter übertragen wurden,
- vom Benutzer separat heruntergeladene Exporte.

Betreiber müssen hierfür eigene Lösch- und Auskunftsprozesse definieren. Eine
automatische Aufbewahrungsfrist ist nicht implementiert.

## Empfohlene Richtlinie

Vor Produktivbetrieb dokumentieren:

1. Zweck und Rechtsgrundlage je Funktion,
2. aktivierte Drittanbieter und Datenregionen,
3. Aufbewahrungs- und Backup-Löschfristen,
4. Zugriffsberechtigungen und Incident-Prozess,
5. Verfahren für Auskunft, Export, Berichtigung und Löschung.
