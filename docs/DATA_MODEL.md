# Data Model

**Scope:** Database schema and image storage conventions. Shared knowledge for both backend and frontend. For API shape and how the backend reads/writes these tables, see [BACKEND.md](./BACKEND.md). For how the frontend consumes filter values and result shapes, see [FRONTEND.md](./FRONTEND.md).

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

Topics belong to a **(Subject, Stream)** pair. The same subject can have a different topic list per stream — e.g. "G2 Math" and "G3 Math" can each define their own topics under `Subject = "Math"`. Topic names need only be unique within a `(subject, stream)`, so "Algebra" can exist independently under both G2 Math and G3 Math.

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
  created_at
}

Question: {
  id,
  paper_id (FK),
  question_number (int),
  marks (int, nullable),
  created_at
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
  question_id (PK, FK → Question),
  topic_id    (PK, FK → Topic),
  PRIMARY KEY (question_id, topic_id)    -- composite PK; referenced by QuestionSubtopic FK
}

QuestionSubtopic: {
  question_id (FK → Question),
  subtopic_id (FK → Subtopic),
  topic_id (NOT NULL),
  PRIMARY KEY (question_id, subtopic_id),
  FK (question_id, topic_id) → QuestionTopic  -- enforces subtopic is under the question's topic
}

User: {
  id,
  email (unique),
  password_hash,
  role ENUM('admin', 'public', 'premium'),   -- 'public' is shown as "Normal" in the UI
  created_at
}

GenerationConfig: {
  id,                          -- singleton: CHECK (id = 1)
  subtitle1_placeholder,       -- grey hint text for Subtitle 1 on the Generate form
  subtitle2_placeholder,       -- grey hint text for Subtitle 2
  cover_body (text),           -- rich-text HTML cover letter stamped on non-admin PDFs
  header_text (text),          -- branding preset: right-aligned on the top rule of every page
  additional_instructions (text), -- instructions preset below the top rule, question paper page 1
  footer_text                  -- footer preset, printed flush-left on every page
}
```

**Generation config.** `GenerationConfig` is a **single row** (`ck_generation_config_singleton`
enforces `id = 1`) of admin-set presets applied to every non-admin paper generation; `CoverTitle`
is the admin-curated list of cover titles those users must pick from (admins may type free text).
The Alembic migration seeds the row with the canonical defaults (mirrored in
`app/services/generation_config.py`, which also lazily re-creates the row if missing) and one
title, `"Topical Worksheets"`. See
[BACKEND.md](./BACKEND.md#generation-config--cover-titles-implemented) for the API and
enforcement rules.

**Roles & the premium paywall.** `role` has three tiers, enforced by a DB check
constraint (`ck_user_role`): `admin`, `public` (labelled "Normal" in the UI), and
`premium`. Premium is granted by an admin via the User Management page (there is no
self-serve payment yet — the Subscribe page is a stub). A paper flagged
`is_premium = true` is gated: only `admin` and `premium` users may view its question
images or generate papers from its questions. Non-premium (and anonymous) users still
see the question tiles and all metadata, but the backend withholds the image URLs.

## Image Storage Conventions

- **Format:** WebP at quality 85 (best size/quality ratio for web; ~30–50% smaller than JPEG at same quality). Fall back to JPEG if WebP encoding is problematic.
- **Storage backend:** AWS S3.
- **Object key pattern:**
  ```
  papers/{paper_id}/q{question_number}/{page_type}_{page_order}.webp
  ```
  Groups all assets for a single question together.

## Image Dimension Standards

These rules apply at import time when the server converts PDF pages to images. They directly shape the values stored in `QuestionPage.width_px` and `QuestionPage.height_px`, which the paper-generation engine uses for layout math.

- **Do NOT resize to A4 aspect ratio.** Page heights vary across questions; only width is normalized.
- **Store content-only images (no baked margin).** Page margins and question numbers are added later, by the paper-generation engine — not at import.
- **Cap width at 1760 px:** if an image is wider than **1760 px**, downscale it to 1760 px preserving aspect ratio; if it is at or below 1760 px, keep it unchanged (never upscale at import). This one rule is applied to every page regardless of question/answer type. The generation engine handles the two types differently: question images are scaled up to exactly 1760 px and centered on the 2480 px page (360 px margin each side); answer images keep their stored width (≤ 1760 px), flush to a 360 px left margin.
- **Store actual dimensions** (`width_px`, `height_px`) in `QuestionPage` so the layout engine can compute page-fit decisions without re-reading image headers.
