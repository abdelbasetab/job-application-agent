# Live-Demo mit echtem Gmail — der geschlossene Kreislauf

**Idee:** Alles ist echt — echte E-Mail über Ihr Gmail, echter Anhang, echter
Inbox-Sync. Nur der „Arbeitgeber" sind Sie selbst: Die Musteranzeige unten
enthält **Ihre eigene Gmail-Adresse als Bewerbungsadresse**. Die App schickt
die Bewerbung also an Sie, Sie antworten aus Gmail „als Firma", und die App
erkennt die Antwort live und stellt den Status auf „Interview" um. Kein Fake —
ein echter Rundlauf.

---

## 1. Einmalige Vorbereitung (10 Minuten)

### .env anpassen (danach Server neu starten!)

```dotenv
EMAIL_DRY_RUN=false          # echte E-Mails senden (nur an Sie selbst!)
EMAIL_SYNC_DRY_RUN=false     # Inbox-Antworten wirklich in Status umsetzen
```

Gmail ist bereits per OAuth verbunden (Einstellungen → Badge „verbunden") —
SMTP/IMAP laufen dann über XOAUTH2, App-Passwörter braucht es nicht.

### Sicherheit (deshalb kann nichts schiefgehen)

- Die Demo-Jobs enthalten **keine** echten E-Mail-Adressen — ohne manuell
  eingetragenen Empfänger geht nichts raus.
- Die Musteranzeige unten enthält als einzige Adresse **Ihre eigene**.
- Vor jedem Klick auf „E-Mail senden": Empfängerfeld ansehen — da muss Ihre
  Adresse stehen.
- **Für die Sende-Szene den LLM-Writer AUS lassen** (Schalter „Semantische
  Bewertung" aus): Das Template-Anschreiben enthält garantiert keine Wörter,
  die der Inbox-Sync später fälschlich als „Interview" deuten könnte
  (z. B. „kennenlernen").

### Nach dem Dreh zurückdrehen

```dotenv
EMAIL_DRY_RUN=true
EMAIL_SYNC_DRY_RUN=true
```

---

## 2. Die Musteranzeige (in die URL-Inbox einfügen)

In der App: **Inbox → „Anzeige einfügen & sofort bewerten"**.
Titel: `Werkstudent KI (m/w/d)` · Unternehmen: `RuhrTech GmbH` ·
Standort: `Gelsenkirchen` — und diesen Text ins Textfeld:

```text
Die RuhrTech GmbH entwickelt KI-Lösungen für den industriellen Mittelstand
in Gelsenkirchen. Zur Verstärkung unseres Teams suchen wir ab sofort einen
Werkstudenten (m/w/d) im Bereich KI.

Deine Aufgaben:
- Du baust LLM-Prototypen und Auswertungen für Kundenprojekte.
- Du unterstützt das Team bei Datenaufbereitung und Evaluation.

Dein Profil:
- Python
- SQL
- Git

Wir bieten flexible Arbeitszeiten neben dem Studium, moderne Ausstattung
und ein hilfsbereites Team. Sehr gute Deutschkenntnisse sind erwünscht.

Bewerbung bitte per E-Mail an: adessadess1990@gmail.com
Ansprechpartnerin: Frau Miriam Schneider
```

Warum das funktioniert: Die Empfänger-Extraktion erkennt „Bewerbung … an:"
als Bewerbungskontext und schlägt **Ihre Adresse automatisch im
Empfängerfeld vor**. Die Anrede im Anschreiben wird „Sehr geehrte Frau
Miriam Schneider" — sieht im Video hervorragend aus.

---

## 3. Ablauf während der Aufnahme (ersetzt Szene 2:20–3:15 im Drehbuch)

1. **Bewerten:** In der Inbox auf „Bewerten" → Score erscheint (voller
   Match: Python, SQL, Git + Standort). „In ‚Suche' öffnen" klicken.
2. **Anschreiben zeigen:** Entwurf mit Anrede „Frau Miriam Schneider" +
   grüne Quality-Checks.
3. **Senden:** Empfängerfeld zeigt schon Ihre Gmail-Adresse (Vorschlag aus
   der Anzeige) · „CV anhängen" an · **„E-Mail senden"** → Status springt
   auf „Eingereicht".
4. **Beweis:** Zweiter Tab (oder Handy ins Bild): Gmail öffnen — da liegt
   die Bewerbung, mit Anschreiben im Text und **lebenslauf.pdf im Anhang**.
   Kurz das PDF antippen: die Match-Skills stehen oben („Fokus für diese
   Bewerbung").
5. **Als „Firma" antworten:** In Gmail auf **Antworten** (Betreff bleibt
   automatisch „Re: Bewerbung: Werkstudent KI (m/w/d) - RuhrTech GmbH" —
   genau daran erkennt die App den Job). Text:

   ```text
   Sehr geehrter Herr Abidi,

   vielen Dank für Ihre Bewerbung. Wir möchten Sie gerne zu einem
   Vorstellungsgespräch einladen. Passt Ihnen kommende Woche Dienstag?

   Mit freundlichen Grüßen
   Miriam Schneider, RuhrTech GmbH
   ```

   („Vorstellungsgespräch" ist das Schlüsselwort für die Erkennung.)
6. **Der Magic-Moment:** Zurück in der App → **„Inbox prüfen"** →
   Status wechselt live auf **„Interview"**, mit Notiz „Inbox: interview
   erkannt von …". Kurz in „Bewerbungen" zeigen: Statistik zählt mit.
7. **Abschluss der Story:** „Interview-Vorbereitung" klicken → der
   Leitfaden für genau diese Stelle erscheint. Perfekter Übergang zum
   Video-Schluss.

**Timing-Tipp:** Gmail-Zustellung an sich selbst dauert 5–30 Sekunden.
Einfach weiterreden oder an dieser Stelle schneiden — niemand erwartet
Echtzeit ohne Schnitt.

---

## 4. Optionale Zusatzszene: Absage → Statistik (20 Sek.)

Vorher einen **zweiten** Musterjob genauso einfügen (Titel z. B.
„Werkstudent Data Analytics", gleiche Kontaktzeile), bewerben und aus Gmail
mit „…müssen wir Ihnen **leider absagen**…" antworten → Sync → Status
„Absage". Danach zeigt **Muster & Statistik** echte Quoten (1 Interview,
1 Absage, Antwortquote 100 %) — sehr überzeugend.

## 5. Optionale Königsdisziplin: Autopilot sendet wirklich (30 Sek.)

Nur wenn Sie es zeigen wollen — **einen Tag vorher**:

1. `.env`: zusätzlich `EMAIL_AUTO_FOLLOW_UP_SEND=true` (+ Neustart).
2. Musterjob Nr. 3 einfügen, bewerben, senden, Status „Eingereicht" —
   dann bis zum Drehtag warten.
3. Im Video: Follow-ups → „Fällig nach: 1 Tag" → **„Autopilot jetzt
   ausführen"** → die App verschickt die Nachfass-Mail **echt** an Ihr
   Gmail (Empfänger kommt aus der Anzeige) — im zweiten Tab trifft sie ein.
4. **Nach dem Dreh sofort zurück auf `false`.**

---

## 6. Troubleshooting

| Problem | Lösung |
| --- | --- |
| Antwort wird nicht erkannt | Betreff muss Titel/Firma enthalten (einfach auf die Original-Mail antworten, nichts umbenennen); „Inbox prüfen" erneut klicken |
| Mail kommt nicht an | Gmail „Alle Nachrichten"/Spam prüfen; selbst-adressierte Mails landen normal im Posteingang |
| Status springt nicht um | `.env`: `EMAIL_SYNC_DRY_RUN=false` gesetzt und Server neu gestartet? |
| Falscher Empfänger im Feld | Immer manuell prüfen — es darf nur Ihre Adresse drinstehen |
| OAuth-Token abgelaufen | Passiert automatisch beim Sync (Refresh); sonst Einstellungen → neu verbinden |
