# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`docs/GLOSSARY.md`** — the domain glossary (single context; there is no `GLOSSARY-MAP.md`).
- **`docs/adr/`** — read ADRs that touch the area you're about to work in.

If either is missing, **proceed silently**. Don't flag its absence; don't suggest creating it upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved — in these locations, not at the repo root. If one ever appears at the root (`GLOSSARY.md`, or an older skill's `CONTEXT.md`), merge it into `docs/GLOSSARY.md` and delete it.

## File structure

```
/
├── docs/
│   ├── GLOSSARY.md
│   └── adr/
│       ├── 0001-stage-pipeline.md
│       └── 0002-qa-booklet-pairing.md
├── app/
├── frontend/
└── ingestion/
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `docs/GLOSSARY.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders) — but worth reopening because…_
