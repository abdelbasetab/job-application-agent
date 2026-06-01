# Sprint 1 — Präsentationsdiagramme

> Render-Tool: https://mermaid.live  
> Einfach den Code-Block reinkopieren → Screenshot für PowerPoint

---

## Diagramm 1: System-Architektur (Gesamtüberblick)

```mermaid
flowchart TD
    User(["👤 Kandidat\n(UserProfile)"])
    CLI["⌨️ CLI\njob-agent run-pipeline"]
    Pipeline["🔄 Pipeline Orchestrator\npipeline.py"]

    Scout["🔍 Scout\nFindet passende Jobs"]
    Matcher["🎯 Matcher\nBewertet Job-Fit"]
    Filter{"Score ≥ 0.5?"}
    Writer["✍️ Writer\nSchreibt Anschreiben"]
    Tracker["📋 Tracker\nSpeichert Status"]
    DB[("💾 SQLite\nDatenbank")]
    Skip(["❌ Zu gering\n→ Übersprungen"])

    User --> CLI --> Pipeline
    Pipeline --> Scout
    Scout -->|"list[JobPosting]"| Matcher
    Matcher -->|"list[MatchResult]"| Filter
    Filter -->|"Ja"| Writer
    Filter -->|"Nein"| Skip
    Writer -->|"GeneratedApplication"| Tracker
    Tracker -->|"ApplicationStatus"| DB

    style Scout fill:#4A90D9,color:#fff
    style Matcher fill:#7B68EE,color:#fff
    style Writer fill:#50C878,color:#fff
    style Tracker fill:#FF8C00,color:#fff
    style DB fill:#888,color:#fff
    style Skip fill:#ccc,color:#555
```

---

## Diagramm 2: Pydantic Schemas — Die Verträge zwischen den Agents

```mermaid
flowchart LR
    Scout["🔍 Scout"] -->|"list[JobPosting]"| Matcher["🎯 Matcher"]
    Matcher -->|"list[MatchResult]"| Writer["✍️ Writer"]
    Writer -->|"GeneratedApplication"| Tracker["📋 Tracker"]
    Tracker -->|"ApplicationStatus"| DB[("💾 SQLite")]

    subgraph S1 ["JobPosting"]
        jp["id, source, url\ntitle, company, location\nrequirements: list[str]\nemployment_type, remote"]
    end

    subgraph S2 ["MatchResult"]
        mr["job_id\nscore: float  ← 0.0–1.0\nmatched_skills\nmissing_skills\nrationale"]
    end

    subgraph S3 ["GeneratedApplication"]
        ga["job_id\ncover_letter_md\ncv_adjustments\ngenerated_at"]
    end

    subgraph S4 ["ApplicationStatus"]
        as_["job_id\nstatus: draft→submitted\n→interview→offer\nupdated_at"]
    end

    Scout -.-> S1
    Matcher -.-> S2
    Writer -.-> S3
    Tracker -.-> S4

    style S1 fill:#E8F4FD,stroke:#4A90D9
    style S2 fill:#F0EBF8,stroke:#7B68EE
    style S3 fill:#EAFAF1,stroke:#50C878
    style S4 fill:#FEF3E2,stroke:#FF8C00
```

---

## Diagramm 3: Scout Agent — CrewAI Innenleben

```mermaid
flowchart TD
    Input(["UserProfile\n+ query + limit"])

    subgraph CrewAI ["CrewAI Framework"]
        direction TB
        LLM["🤖 LLM\nclaude-sonnet-4-6\n(Anthropic)"]

        subgraph Agent ["Scout Agent"]
            Role["role: 'Job Scout'"]
            Goal["goal: 'Find matching jobs in Germany'"]
            Backstory["backstory: 'Expert in German tech market,\nnever invents requirements'"]
        end

        subgraph TaskBox ["Task"]
            Desc["description:\n'Create {limit} job postings\nfor this candidate: {profile_json}'"]
            ExpOut["expected_output:\n'JSON array of JobPosting objects'"]
        end

        Crew["Crew.kickoff()"]
        Agent --> TaskBox
        LLM --> Agent
        TaskBox --> Crew
    end

    subgraph Parse ["Output-Verarbeitung"]
        Strip["Strip Markdown-Fences\n(```json ... ```)"]
        JSON["json.loads(raw)"]
        Validate["JobPosting.model_validate()\nfür jeden Eintrag"]
    end

    Input --> CrewAI
    Crew -->|"raw string"| Strip
    Strip --> JSON --> Validate
    Validate --> Output(["list[JobPosting]\n✅ validiert"])

    style CrewAI fill:#FDF6E3,stroke:#DAA520
    style Parse fill:#F0F8FF,stroke:#4682B4
    style LLM fill:#FF6B6B,color:#fff
```

---

## Diagramm 4: Matcher — Scoring-Logik (Sprint 1)

```mermaid
flowchart LR
    P["👤 profile.skills\n['python','sql','llms','git']"]
    J["📄 job.requirements\n['python','llms','docker']"]

    Intersect{"Schnittmenge\n∩"}
    P --> Intersect
    J --> Intersect

    Matched["matched = ['python','llms']\n→ 2 von 3 ✅"]
    Missing["missing = ['docker']\n→ 1 von 3 ❌"]

    Score["score = 2/3 = 0.667"]
    Bonus{"nice_to_have\n∩ profile?"}
    BonusY["+0.1 Bonus"]
    BonusN["kein Bonus"]
    Final["final score = min(0.767, 1.0)"]

    Intersect --> Matched & Missing
    Matched --> Score
    Score --> Bonus
    Bonus -->|"Ja"| BonusY --> Final
    Bonus -->|"Nein"| BonusN --> Final

    style Matched fill:#EAFAF1,stroke:#50C878
    style Missing fill:#FDEDEC,stroke:#E74C3C
    style Final fill:#4A90D9,color:#fff
```

---

## Diagramm 5: Sprint-Roadmap

```mermaid
gantt
    title Job Application Agent — Sprint-Plan
    dateFormat  YYYY-MM-DD
    section Sprint 1
    Schemas + Scaffold         :done,    s1a, 2026-05-01, 7d
    Matcher / Writer / Tracker :done,    s1b, 2026-05-01, 7d
    Scout (CrewAI)             :active,  s1c, 2026-05-08, 5d
    section Sprint 2
    Scout: Adzuna + BA-API     :         s2a, 2026-05-13, 7d
    Dedup-Guard im Tracker     :         s2b, 2026-05-13, 7d
    section Sprint 3
    Matcher: LLM-Scoring       :         s3a, 2026-05-20, 7d
    Writer: LLM-Anschreiben    :         s3b, 2026-05-20, 7d
    section Sprint 4
    ChromaDB Embeddings        :         s4a, 2026-05-27, 7d
    No-Duplicate Guard         :         s4b, 2026-05-27, 7d
    section Sprint 5
    Streamlit Dashboard        :         s5a, 2026-06-03, 7d
    Evaluation + Demo          :         s5b, 2026-06-03, 7d
```

---

## Wie du die Diagramme verwendest

1. Gehe zu **https://mermaid.live**
2. Kopiere einen Code-Block (zwischen den ` ``` ` Zeichen)
3. Füge ihn links im Editor ein → rechts siehst du das Diagramm
4. Klicke **PNG** oder **SVG** zum Download
5. Bild in PowerPoint/Keynote einfügen
