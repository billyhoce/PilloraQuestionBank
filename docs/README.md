# Documentation

Docs are organised **by feature**, not by layer: each file under [`features/`](./features) covers one
capability end-to-end — its API, its UI, and any AI or PDF work it involves — so you can answer a
question by reading one file instead of three.

## Start here

| Doc | What's inside |
|---|---|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Stacks, backend/frontend code layout, object-store integration, routes, navigation, cross-cutting conventions |
| [DATA_MODEL.md](./DATA_MODEL.md) | Database schema (reference + core tables), image storage conventions, image dimension standards |

## Features

| Doc | What's inside |
|---|---|
| [features/auth.md](./features/auth.md) | Registration, password login, Google OAuth 2.0, JWT sessions, security posture, auth UI |
| [features/users-and-premium.md](./features/users-and-premium.md) | The three tiers, user management, the `is_premium` flag, how the paywall is enforced |
| [features/reference-data.md](./features/reference-data.md) | Subjects/streams/levels/schools/exam types/topics CRUD + admin UI |
| [features/ingestion.md](./features/ingestion.md) | Manual import (wizard, PDF→image, confirm/delete), Manage Papers editor, provenance |
| [features/auto-import.md](./features/auto-import.md) | Auto-detect import: direct-to-S3 upload, ingest jobs, worker, review/confirm, retention + reconciler, logs/events/cost |
| [features/qa-pairing.md](./features/qa-pairing.md) | Answer-only papers, attach to an existing paper, Match panel, automatic matching, linked confirm |
| [features/ai-labelling.md](./features/ai-labelling.md) | Claude part-split + topic/marks labelling, paper metadata extraction, parts write path, review UI, costs |
| [features/browse.md](./features/browse.md) | `/api/questions` filtering + search, filter panel and results UI |
| [features/paper-generation.md](./features/paper-generation.md) | Selection algorithms, generate endpoints, role enforcement, `/generate` UI |
| [features/generation-config.md](./features/generation-config.md) | Admin presets + cover titles that constrain non-admin generations |
| [features/site-config.md](./features/site-config.md) | Public About page + its WYSIWYG editor and sanitizer, and the image-copy deterrent toggle |
| [../ingestion/README.md](../ingestion/README.md) | The PDF ingester package (booklet segmentation, splitting, question-rectangle location, answer tables + OCR); verified by diffing `ingestion/samples/` output, not by unit tests |
| [features/pdf-rendering.md](./features/pdf-rendering.md) | Layout engine, packing, page chrome, cover page, rich-text cover body |

## Plans

| Doc | What's inside |
|---|---|
| [plans/ingest-hardening-and-qa-pairing.md](./plans/ingest-hardening-and-qa-pairing.md) | Implemented (except #81 duplicate-paper protection): kept for its decisions and rationale; behaviour lives in the feature docs |

## Decisions

| Doc | What's inside |
|---|---|
| [adr/0001-stage-pipeline.md](./adr/0001-stage-pipeline.md) | The ingestion stage pipeline |
| [adr/0002-qa-booklet-pairing.md](./adr/0002-qa-booklet-pairing.md) | Question/answer booklet pairing |

## Operations

| Doc | What's inside |
|---|---|
| [DEPLOYMENT.md](./DEPLOYMENT.md) | Hosting plan, CI/CD, VM provisioning, env vars, Google OAuth setup, backups |
| [PDF_GENERATION_TESTING.md](./PDF_GENERATION_TESTING.md) | DB-free sample-PDF generation and the visual self-verification loop |

Local dev setup, testing commands, and the git workflow are in the root
[README.md](../README.md).
