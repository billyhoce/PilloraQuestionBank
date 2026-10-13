# Data Model

**Scope:** Database schema and image storage conventions — the shared reference every feature builds
on. For how a given table is read and written, see the matching doc under
[`features/`](./features) (indexed in [README.md](./README.md)).

## Reference Tables (Admin CRUD)

```
SchoolLevel:    { id, name }                          -- "primary", "secondary"
Subject:        { id, name }                          -- e.g. "Math", "Science"
Stream:         { id, name, school_level_id (FK) }    -- e.g. "G1", "G2", "G3", "Foundation", "Standard"
Level:          { id, name, sort_order, school_level_id (FK) }
School:         { id, name }
ExamType:       { id, name }                          -- e.g. "WA1", "WA2", "EOY", "Prelim"
Topic:          { id, subject_id (FK), stream_id (FK), name, topic_number }
Subtopic:       { id, topic_id (FK), name }
CoverTitle:     { id, name (unique) }                 -- cover titles users pick from when generating
```

### Key Relationship

Topics belong to a **(Subject, Stream)** pair. The same subject can have a different topic list per stream — e.g. "G2 Math" and "G3 Math" can each define their own topics under `Subject = "Math"`. Topic names need only be unique within a `(subject, stream)`, so "Algebra" can exist independently under both G2 Math and G3 Math. See [features/reference-data.md](./features/reference-data.md).

## Core Tables

```
Paper: {
  id,
  subject_id (FK),
  stream_id (FK),
  level_id (FK),
  school_id (FK),
  exam_type_id (FK),
  year (int),
  paper_number (string),       -- "1", "2", "a", "b" etc.
  is_premium (bool),           -- default false; premium papers are gated to premium/admin users
  created_by (FK -> User),
  created_at,
  source_job_id (uuid, nullable FK -> IngestJob, ON DELETE SET NULL)  -- provenance: the auto-import job that produced it (set when the review page confirms it); NULL for manual imports
}

Question: {
  id,
  paper_id (FK),
  question_number (int),
  section (string(64), nullable),            -- provenance: the proposal paper's question label (e.g. "q1"); NULL for manual imports
  proposal_question_index (int, nullable),   -- provenance: 0-based index in that proposal paper's `questions`; NULL for manual imports
  created_at
  -- no marks column: the total is SUM(QuestionPart.marks), see below
}

QuestionPart: {
  id,
  question_id (FK → Question, ON DELETE CASCADE),
  part_order (int),            -- 0-based; ordering within this question
  label (string(32)),          -- "(a)", "(a)(i)", "" for an unparted question
  marks (int, nullable),
  UNIQUE (question_id, part_order),
  CHECK (part_order >= 0)
}

QuestionPage: {
  id,
  question_id (FK),
  page_order (int),            -- ordering within this question
  image_key (string),          -- object store key/path
  page_type ENUM('question', 'answer'),
  width_px (int),              -- stored image width in pixels
  height_px (int)              -- stored image height in pixels (varies per page)
}

QuestionTopic: {
  part_id  (PK, FK → QuestionPart),
  topic_id (PK, FK → Topic),
  PRIMARY KEY (part_id, topic_id)        -- composite PK; referenced by QuestionSubtopic FK
}

QuestionSubtopic: {
  part_id (FK → QuestionPart),
  subtopic_id (FK → Subtopic),
  topic_id (NOT NULL),
  PRIMARY KEY (part_id, subtopic_id),
  FK (part_id, topic_id) → QuestionTopic  -- enforces subtopic is under the part's topic
}

Tag: {
  id,
  name (unique)
}

QuestionTag: {
  question_id (PK, FK → Question),
  tag_id      (PK, FK → Tag),
  PRIMARY KEY (question_id, tag_id)      -- tags are question-level, not per part
}

User: {
  id,
  email (unique),                            -- always lower-cased; see normalize_email()
  first_name,                                -- '' for accounts predating the field
  last_name,                                 -- '' for accounts predating the field
  password_hash (nullable),                  -- NULL for accounts created via Google, and for
                                             --   an admin-created invite nobody has claimed
  google_sub (unique, nullable),             -- Google's 'sub' claim; set once linked to Google
  role ENUM('admin', 'public'),              -- 'public' is shown as "Normal" in the UI
  created_at,
  last_login_at (nullable),                  -- stamped on every successful sign-in, both paths;
                                             --   NULL until the account has ever signed in
  papers_generated (int, default 0)          -- running count from POST /api/generate/paper
}

UserPremiumSchoolLevel: {
  user_id         (PK, FK → app_user,     ON DELETE CASCADE),
  school_level_id (PK, FK → school_level, ON DELETE CASCADE),
  PRIMARY KEY (user_id, school_level_id)
}

GenerationConfig: {
  id,                          -- singleton: CHECK (id = 1)
  subtitle1_placeholder,       -- grey hint text for Subtitle 1 on the Generate form
  subtitle2_placeholder,       -- grey hint text for Subtitle 2
  cover_body (text),           -- rich-text HTML cover letter stamped on non-admin PDFs
  header_text (text),          -- branding preset: right-aligned on the top rule of every page
  additional_instructions (text), -- instructions preset below the top rule, question paper page 1
  footer_text (text)           -- footer preset, printed flush-left on every page

  -- All four text fields hold the same rich-text HTML subset (paragraphs plus
  -- bold/italic/underline/link), sanitized at render time by app/pdf/rich_text.py.
  -- Plain text stored before they became rich text still renders, and migration
  -- a1b2c3d4e5f7 converts the seeded values to HTML.
}

SiteConfig: {
  id,                          -- singleton: CHECK (id = 1)
  about_content (text),        -- rich-text HTML for the public /about page
  protect_images (bool)        -- default false; client-side deterrent against
                               --   copying question images

  -- A separate singleton from GenerationConfig because that one is scoped to
  -- paper-generation presets and its endpoint requires auth, while BOTH fields
  -- here must reach signed-out visitors. about_content is a WIDER HTML subset
  -- (headings, lists, colour, font size) than the PDF fields above, and is
  -- sanitized on WRITE by app/services/site_config.py rather than at render
  -- time, because it is the one value rendered as HTML in the browser.
}
```

### Questions have parts

A real exam question is made of parts — (a), (b), and often (a)(i)/(a)(ii) — and
each part tests a different topic and is worth its own marks. **Topics,
subtopics and marks therefore hang off `QuestionPart`, never off `Question`.**

- **Every question has at least one part.** A question with no printed parts is
  modelled as a single part whose `label` is `''`. The invariant is enforced in
  code (`app/services/question_parts.py`), not by a DB constraint.
- **`label` is the paper's own text**, e.g. `"(a)(i)"`. It cannot be derived
  from `part_order`, because `(a)(i)`, `(a)(ii)` and `(b)` are three independent
  parts — so positional lettering would render the third as "(c)" and mislead an
  admin checking it against the question image.
- **A question's marks total is derived, never stored**: `SUM(QuestionPart.marks)`,
  exposed on the ORM as `Question.total_marks` (a `column_property`) and
  serialized as `marks` in the API. It is `NULL` when no part carries marks,
  which the generation selectors already treat as "unmarked". Because it is
  computed, the total can never disagree with the parts.
- **Images are not split per part.** A question is imported as one set of page
  images covering all its parts; splitting is purely a labelling concern, done
  by the AI labeller and corrected by the admin. See
  [features/ai-labelling.md](./features/ai-labelling.md).

Deleting a part cascades to its `QuestionTopic` and `QuestionSubtopic` rows, so
replacing a question's labelling is a single delete-then-insert of its parts.

**Generation config.** `GenerationConfig` is a **single row** (`ck_generation_config_singleton`
enforces `id = 1`) of admin-set presets applied to every non-admin paper generation; `CoverTitle`
is the admin-curated list of cover titles those users must pick from (admins may type free text).
The Alembic migration seeds the row with canonical defaults and one title, `"Topical Worksheets"`.
See [features/generation-config.md](./features/generation-config.md).

**Roles & the premium paywall.** `role` has just two values, enforced by a DB check constraint
(`ck_user_role`): `admin` and `public` (labelled "Normal" in the UI).

**Premium is not a role — it is a set of school levels.** It is sold per school level (Primary and
Secondary are separate products) and a user may hold several, so it lives in
`UserPremiumSchoolLevel` rather than in `role`. Like `Question.total_marks`, "is this user premium"
is **derived, never stored**, so it can never disagree with what the user can actually open.

A paper flagged `is_premium = true` unlocks for admins and for users holding **its own school
level**, which is the one on its `level` (`paper.level.school_level_id`). A paper reaches a school
level through its `stream` too, so paper writes reject the two disagreeing with a 422 — otherwise a
paper could read as Secondary in the UI while being sold to Primary customers. The policy lives in
`app/services/premium.py`; see [features/users-and-premium.md](./features/users-and-premium.md).

**Names.** `first_name` / `last_name` are `NOT NULL DEFAULT ''`. Manual registration requires both
(non-blank, ≤100 chars); Google supplies them from `given_name` / `family_name`, which it does not
always send. Rows created before this field existed keep `''`, so the UI falls back to the email
address wherever a name is displayed (`frontend/src/utils/userName.js`).

**Emails are stored lower-cased.** Every write and every lookup goes through `normalize_email`
(`app/services/auth.py`); migration `e6f7a8b9c0d1` folded the rows written before it existed. Google's
OIDC `email` claim is canonical lower-case, so matching verbatim meant one person could end up with
two accounts. Only case and surrounding whitespace fold — Gmail's dot and `+` aliases deliberately do
**not**, since they are provider-specific and folding them would be wrong for every other provider.

**Google-linked accounts.** `google_sub` holds Google's `sub` claim — unique per Google account and
stable even if the user changes the email address on it, which is why sign-in matches on it rather
than on email. The two credential columns give **four** states:

| `password_hash` | `google_sub` | What the row is |
|---|---|---|
| set | NULL | Manual registration |
| NULL | set | First sign-in with Google |
| set | set | Registered manually, later signed in with Google on the same verified address |
| NULL | NULL | **An admin-created invite nobody has claimed yet** — no way to sign into it |

The third row is produced by **auto-linking**: when Google reports `email_verified = true` for an
address that already has an account, that account gains the `google_sub` and keeps its existing
`role` **and premium school levels** — Google has proven ownership of the address, so this is safe,
and it avoids a duplicate account. Both sign-in methods then work. Blank names are backfilled from Google at that point, but
a name the user typed is never overwritten. `password_hash` is nullable purely to represent the
second row; `verify_password` rejects a NULL/empty hash, so a Google-only account cannot be
password-logged-in.

The fourth row is an **invite** (`User.is_invited`, derived rather than stored — like premium access,
so it can never disagree with the credentials actually present). It is created by
`POST /api/users` so premium is live before the customer signs up, and it is *claimed* — becoming
row one or row two — when someone registers with that address or signs in with Google on it, keeping
its role and entitlements either way. See [features/auth.md](./features/auth.md) and
[features/users-and-premium.md](./features/users-and-premium.md).

## Auto-import jobs

Tables behind the Auto-detect import ([features/ingestion.md](./features/ingestion.md#auto-detect-import)).
Postgres types (`ENUM`, `JSONB`, `INT[]`) have portable variants in the ORM so the SQLite unit-test
schema still builds (`JSON().with_variant(JSONB, "postgresql")`).

```
IngestJob: {
  id (uuid, PK),
  created_by (FK -> User, ON DELETE RESTRICT),
  filename, source_key,          -- source_key = ingest/{id}/source.pdf (legacy jobs: tmp/ingest/{id}/source.pdf)
  sha256, page_count,            -- nullable: NULL until the worker's `register` task reads the PDF (and for a PDF it rejected)
  status ENUM(awaiting_upload, queued, running, review_ready, failed, confirmed, cancelled, expired),  -- default queued
  proposal (JSONB, nullable),    -- the pipeline's proposed split
  proposal_edited (JSONB, nullable),  -- the admin's edits to it
  report (JSONB, nullable),      -- run report; `paper_metadata` maps each proposal paper's key to the
                                 -- metadata read from its cover, written by the worker's `segment` task (pre-fills
                                 -- the metadata sidebar; old jobs have `filename_metadata` instead);
                                 -- `review_outcome` maps each proposal paper's key to "confirmed" | "skipped"
                                 -- (written by the confirm/skip endpoints; the job is `confirmed` once all are set)
  debug (JSONB, nullable),       -- debug bundle copied at report time: {"segments": segments.json, "ingest": ingest.json};
                                 -- all that is kept of the worker's scratch once the job is review_ready/settled
  error (text, nullable),
  created_at, updated_at,
  confirmed_paper_ids (int[], nullable)   -- papers created by confirming proposal papers, in order
}

IngestTask: {
  id,
  job_id (FK -> IngestJob, ON DELETE CASCADE),
  section (string(8), nullable), -- NULL for job-level stages
  stage (string(16)),
  status ENUM(pending, ready, running, done, skipped, failed, blocked),  -- default pending
  attempts (int), reason, error (text),
  traceback (text, nullable),  -- last ~4 KB of the traceback of the exception a failed stage raised
  warnings (JSONB, default []),
  needs_review (bool), fingerprint (string(64), nullable),
  lease_until, started_at, finished_at (timestamptz, nullable), duration_ms (int, nullable),
  UNIQUE (job_id, section, stage),
  UNIQUE (job_id, stage) WHERE section IS NULL   -- partial index, see below
}

IngestPaper: {                -- one row per paper an ingest job proposed; the queryable mirror of the per-paper
                              -- bits of proposal/report (see "Source of truth" below)
  id,
  job_id (FK -> IngestJob, ON DELETE CASCADE),
  paper_key (string(64)),     -- the proposal's key: question label `q1`, else answer label `a1`, else `paperN`
  role ("question" | "answer_only"),
  school_id, level_id, subject_id, exam_type_id, stream_id (nullable FKs, ON DELETE SET NULL),
  year (int, nullable), paper_number (string(32), nullable),   -- stored as given (no normalisation yet)
  metadata_source ("cover" | "filename" | "admin", nullable),  -- NULL: nothing known
  status ("pending" | "confirmed" | "skipped" | "attached"),   -- default pending
  paper_id (nullable FK -> Paper, ON DELETE SET NULL),         -- the paper confirming it created
  matched_ingest_paper_id (nullable self-FK, ON DELETE SET NULL),  -- set by the manual Match panel (and later automatic matching); both rows of a pair point at each other
  created_at, updated_at,
  UNIQUE (job_id, paper_key)
}
-- Written by the worker's `report` hook in the same transaction as the proposal (an upsert on
-- (job_id, paper_key), so a re-run never duplicates; metadata from report.paper_metadata[key] -> `cover`, else
-- the old report.filename_metadata -> `filename`). `PUT /api/import/jobs/{id}/papers/{key}/metadata`
-- (the review sidebar, debounced) and confirm store the admin's values and set `metadata_source = admin` when a value
-- changed; confirm and skip set `status` (and `paper_id`) in the same transaction as the outcome. `attached` is
-- written by the attach flow (not built yet). Source of truth: `proposal`/`proposal_edited` for the paper's
-- contents and `report.review_outcome` for the decision (the review flow reads only those); `ingest_paper` mirrors
-- role, metadata and status and is what matching reads, kept in step on every write. The migration backfilled
-- a row for every existing job with a proposal (`paper_id` left NULL; ids no longer in the reference tables dropped).

IngestEvent: {                -- append-only audit trail, kept indefinitely (never pruned)
  id,
  job_id (FK -> IngestJob, ON DELETE CASCADE),
  task_id (nullable FK -> IngestTask, ON DELETE SET NULL),
  at (timestamptz), kind (string(32)),
  actor_user_id (nullable FK -> AppUser, ON DELETE SET NULL),  -- the admin; NULL for the worker/sweep
  data (JSONB, default {}),
  INDEX (job_id, id)
}
-- kind: created, task_claimed, task_finished (data.status done/skipped/failed, error, warnings,
-- duration_ms, traceback), retry, cancelled, proposal_edited, paper_confirmed, paper_skipped,
-- expired (historical; no longer written). Task rows are overwritten on claim/reopen; each attempt stays visible here.

WorkerHeartbeat: {             -- singleton
  id (int, CHECK id = 1),
  seen_at, version, current_job_id (nullable FK -> IngestJob, ON DELETE SET NULL),
  last_sweep_at (timestamptz, nullable)   -- when the daily sweep last ran
}
```

A plain `UNIQUE (job_id, section, stage)` does not constrain rows whose `section` is NULL in Postgres
(NULLs are distinct), so job-level tasks get the extra **partial unique index**
`uq_ingest_task_job_stage_jobwide`. It was chosen over `NULLS NOT DISTINCT` because that needs
PG15+, whereas a partial index works on every Postgres and on SQLite (the test DB). A job's first
task is `(section NULL, stage 'register', status 'ready')`.

## Image Storage Conventions

- **Format:** WebP at quality 85 (best size/quality ratio for web; ~30–50% smaller than JPEG at same quality). Fall back to JPEG if WebP encoding is problematic.
- **Storage backend:** AWS S3.
- **Object key pattern:**
  ```
  papers/{paper_id}/q{question_number}/{page_type}_{page_order}.webp
  ```
  Groups all assets for a single question together.
- **Auto-import jobs** keep their data under `ingest/{job_id}/` (`source.pdf`, review `pages/`), a
  prefix with no bucket lifecycle rule; the whole prefix is deleted when the job settles or is
  cancelled. Jobs created before the move still sit under `tmp/ingest/{job_id}/`: every reader
  derives the prefix from the stored `source_key` (`job_prefix`), never from the id.

## Image Dimension Standards

These rules apply at import time when the server converts PDF pages to images (see [features/ingestion.md](./features/ingestion.md)). They directly shape the values stored in `QuestionPage.width_px` and `QuestionPage.height_px`, which the [layout engine](./features/pdf-rendering.md) uses for layout math.

- **Do NOT resize to A4 aspect ratio.** Page heights vary across questions; only width is normalized.
- **Store content-only images (no baked margin).** Page margins and question numbers are added later, by the paper-generation engine — not at import.
- **Cap width at 1760 px:** if an image is wider than **1760 px**, downscale it to 1760 px preserving aspect ratio; if it is at or below 1760 px, keep it unchanged (never upscale at import). This one rule is applied to every page regardless of question/answer type. The generation engine handles the two types differently: question images are scaled up to exactly 1760 px and centered on the 2480 px page (360 px margin each side); answer images keep their stored width (≤ 1760 px), flush to a 360 px left margin.
- **Store actual dimensions** (`width_px`, `height_px`) in `QuestionPage` so the layout engine can compute page-fit decisions without re-reading image headers.
