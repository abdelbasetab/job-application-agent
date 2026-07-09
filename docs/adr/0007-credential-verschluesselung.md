# ADR-0007: Lokale Credential-Verschlüsselung ohne Zusatz-Dependency

Status: akzeptiert (Sprint 5)

## Kontext

Die E-Mail-Integration (SMTP/IMAP-Passwörter, OAuth-Access-/Refresh-Tokens)
braucht persistente Geheimnisse pro Web-Account. Klartext in SQLite wäre
inakzeptabel: `data/` wird gesichert/kopiert, und ein versehentlich geteiltes
Backup dürfte keine Mail-Zugänge preisgeben.

Optionen:

1. **`cryptography` (Fernet/AES-GCM)** — Industriestandard, aber eine große,
   plattformabhängige Binär-Dependency (Rust/OpenSSL-Build) nur für dieses
   eine Feature; erhöht Installations- und CI-Aufwand spürbar.
2. **OS-Keyring** (`keyring`) — plattformabhängiges Verhalten, headless/CI
   problematisch, Docker-Volumes nicht abgedeckt.
3. **Stdlib-Konstruktion** — Stream-Cipher aus SHA-256 (Key + Nonce + Counter)
   mit HMAC-SHA256 im Encrypt-then-MAC-Muster; Schlüssel als zufällige
   32-Byte-Datei (`credentials.key`, chmod 600 best effort) neben der DB.

## Entscheidung

Option 3 für den lokalen Scope dieses Projekts. Begründung:

- **Bedrohungsmodell:** Schutzziel ist „Secrets nicht im Klartext in der DB /
  im Backup" — nicht Schutz gegen einen Angreifer mit vollem Zugriff auf
  dieselbe Maschine (der könnte auch die laufende Anwendung auslesen).
  Schlüsseldatei und DB liegen bewusst im selben Nutzerkontext.
- **Konstruktion statt Eigenbau-Kryptanalyse:** Es werden ausschließlich
  Standard-Primitive der stdlib komponiert (SHA-256-Keystream ≙ CTR-Ansatz,
  HMAC-SHA256, `secrets` für Schlüssel/Nonce, konstantzeitiger Vergleich).
  Encrypt-then-MAC verhindert Manipulation; pro Eintrag frische 16-Byte-Nonce.
- **Betriebsvorteil:** identisches Verhalten auf Windows/Linux/Docker, keine
  native Build-Kette, Tests bleiben schnell und offline.

Der Modul-Docstring erklärt die Grenze ausdrücklich: *„local-first
foundation, not a SaaS-grade secret manager"* — eine SaaS-Variante ersetzt
das Modul durch KMS/Fernet.

## Konsequenzen

- Backups von `data/` enthalten Secrets nur verschlüsselt; wer sie lesen
  will, braucht zusätzlich `credentials.key`.
- Schlüsselrotation = Datei löschen + Konten neu verbinden (dokumentierte,
  bewusst einfache Strategie für den lokalen Einsatz).
- Bei einem Wechsel zu Multi-Host-/SaaS-Betrieb ist der Tausch auf
  Fernet/KMS ein lokal begrenzter Eingriff (eine Klasse, stabile API:
  `save_json` / `load_json` / `delete`).

## Verworfene Alternativen

- **Klartext + Dateirechte:** schützt Backups nicht, fällt bei kopierten
  `data/`-Ordnern sofort.
- **`cryptography` sofort:** kryptografisch die stärkste Wahl, aber für den
  Prüfungs-/Lokal-Scope unverhältnismäßig (Dependency-Gewicht, Build-Risiken
  in CI); als SaaS-Pfad im Modul-Docstring festgehalten.
