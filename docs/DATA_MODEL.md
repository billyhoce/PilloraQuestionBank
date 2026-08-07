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
  created_at
}

Question: {
  id,
  paper_id (FK),
  question_number (int),
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
  email (unique),
  first_name,                                -- '' for accounts predating the field
  last_name,                                 -- '' for accounts predating the field
  password_hash (nullable),                  -- NULL for accounts created via Google
  google_sub (unique, nullable),             -- Google's 'sub' claim; set once linked to Google
  role ENUM('admin', 'public'),              -- 'public' is shown as "Normal" in the UI
  created_at
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

**Google-linked accounts.** `google_sub` holds Google's `sub` claim — unique per Google account and
stable even if the user changes the email address on it, which is why sign-in matches on it rather
than on email. An account may have a password, a Google link, or both:

| `password_hash` | `google_sub` | How it was created |
|---|---|---|
| set | NULL | Manual registration |
| NULL | set | First sign-in with Google |
| set | set | Registered manually, later signed in with Google on the same verified address |

The third row is produced by **auto-linking**: when Google reports `email_verified = true` for an
address that already has an account, that account gains the `google_sub` and keeps its existing
`role` **and premium school levels** — Google has proven ownership of the address, so this is safe,
and it avoids a duplicate account. Both sign-in methods then work. Blank names are backfilled from Google at that point, but
a name the user typed is never overwritten. `password_hash` is nullable purely to represent the
second row; `verify_password` rejects a NULL/empty hash, so a Google-only account cannot be
password-logged-in. See [features/auth.md](./features/auth.md).

## Image Storage Conventions

- **Format:** WebP at quality 85 (best size/quality ratio for web; ~30–50% smaller than JPEG at same quality). Fall back to JPEG if WebP encoding is problematic.
- **Storage backend:** AWS S3.
- **Object key pattern:**
  ```
  papers/{paper_id}/q{question_number}/{page_type}_{page_order}.webp
  ```
  Groups all assets for a single question together.

## Image Dimension Standards

These rules apply at import time when the server converts PDF pages to images (see [features/ingestion.md](./features/ingestion.md)). They directly shape the values stored in `QuestionPage.width_px` and `QuestionPage.height_px`, which the [layout engine](./features/pdf-rendering.md) uses for layout math.

- **Do NOT resize to A4 aspect ratio.** Page heights vary across questions; only width is normalized.
- **Store content-only images (no baked margin).** Page margins and question numbers are added later, by the paper-generation engine — not at import.
- **Cap width at 1760 px:** if an image is wider than **1760 px**, downscale it to 1760 px preserving aspect ratio; if it is at or below 1760 px, keep it unchanged (never upscale at import). This one rule is applied to every page regardless of question/answer type. The generation engine handles the two types differently: question images are scaled up to exactly 1760 px and centered on the 2480 px page (360 px margin each side); answer images keep their stored width (≤ 1760 px), flush to a 360 px left margin.
- **Store actual dimensions** (`width_px`, `height_px`) in `QuestionPage` so the layout engine can compute page-fit decisions without re-reading image headers.
