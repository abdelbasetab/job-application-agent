# ADR-0006: Rubrik als primärer Match-Score (Gewichte, Hard Gate, Level-Deckel)

Status: akzeptiert (Sprint 4)

## Kontext

Bis Sprint 3 berechnete der Matcher zwei Werte: einen Legacy-Score
(Muss-Skill-Quote + 0.1 Nice-to-have-Bonus) und die gewichtete 1-5-Rubrik.
Der Endscore war `max(legacy, rubrik)`. Folge: Sobald alle Muss-Skills
passten, wurde der Score 1.0 — egal wie schlecht Standort, Sprache oder
Inseratsqualität bewertet waren. Die Rubrik war damit in genau den Fällen
wirkungslos, in denen sie differenzieren sollte, und die UI zeigte eine
Aufschlüsselung, die den Endscore gar nicht erklärte.

## Entscheidung

1. **Die gewichtete Rubrik ist der Score.** Der Legacy-Score entfällt.
2. **Gewichte** (Summe 100):

   | Dimension | Gewicht | Begründung |
   | --- | ---: | --- |
   | Muss-Skills | 45 | Wichtigstes Signal; unter 50, damit weiche Faktoren zusammen (55) einen Voll-Match noch abstufen können. |
   | Nice-to-have | 5 | Bonus-Charakter, darf nie dominieren. |
   | Standort/Remote | 15 | Für Werkstudierende real entscheidend (Pendelbarkeit). |
   | Level/Jobtyp | 10 | Grobe Passung; harte Fälle deckt der Level-Deckel ab. |
   | Sprache | 10 | Binär erkennbares K.o.-Kriterium in DE-Inseraten. |
   | Inseratsqualität | 15 | Ghost-Job-/Scam-Signale sollen sichtbar Score kosten. |

3. **Hard Gate:** 0 gedeckte Muss-Skills ⇒ Score 0.0. Ein Rust-Embedded-Job
   wird nicht durch guten Standort „gerettet“.
4. **Level-Deckel:** Seniorität ≤ 2 (klar zu senior für das Profil) deckelt
   den Score bei 0.55 — maximal „prüfen“, nie „sehr guter Fit“. Ein reines
   Gewicht von 10 könnte das nicht leisten (0.92 wäre trotz Senior-Rolle
   möglich gewesen).
5. **Risiko-Penalty** unverändert: medium −0.10, high −0.35, plus
   Empfehlung „skip“ bei hohem Risiko.
6. **Skill-Matching in 3 Stufen** vor der Bewertung: exakt/Alias →
   Ähnlichkeit (Embeddings, sonst Fuzzy-Ratio ≥ 0.84) → LLM-Matcher.

## Konsequenzen

- Ein perfekter Skill-Match ergibt jetzt typischerweise 0.85–1.0 statt
  pauschal 1.0 — die weichen Dimensionen bleiben sichtbar.
  `test_matcher_skill_overlap_scoring` wurde entsprechend angepasst.
- Die Gewichte sind kalibrierbar und werden durch das Golden-Set
  (`job-agent eval`, `tests/test_evaluation.py`) als Regressionsgate
  überwacht: Accuracy ≥ 0.7, Within-1 ≥ 0.9, Kappa ≥ 0.5.
- Bewusste Grenzfälle bleiben dokumentiert im Golden-Set (z.B. voller
  Skill-Match in der falschen Stadt): dort darf der Matcher von der
  menschlichen Einschätzung um eine Stufe abweichen.

## Verworfene Alternativen

- **`max(legacy, rubrik)` behalten** — erklärt den Score nicht und macht die
  Rubrik wirkungslos (siehe Kontext).
- **Blend (z.B. 0.7·Rubrik + 0.3·Legacy)** — zwei Skalen ohne inhaltlichen
  Mehrwert; die Muss-Skill-Quote steckt bereits mit Gewicht 45 in der Rubrik.
- **Seniorität höher gewichten statt Deckel** — hätte alle anderen Dimensionen
  verwässert, obwohl der Mismatch nur im Extremfall (Senior/Lead vs.
  Studierendenprofil) hart durchschlagen soll.
