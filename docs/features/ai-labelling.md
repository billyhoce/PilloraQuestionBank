# AI Labelling

**Scope:** All Anthropic Claude API usage — the per-part split + topic/marks labeller and the
filename metadata extractor — plus the parts write path and the review UI that consume them. The
`QuestionPart` schema is in [DATA_MODEL.md](../DATA_MODEL.md#questions-have-parts); the import steps
around this one are in [ingestion.md](./ingestion.md).

## Part splitting & topic auto-labeling

One call does both jobs: it splits a question into its printed parts and labels each part with the
topics it tests and the marks it is worth. **Images are never split** — a question is one set of page
images covering all its parts, so the split exists only in the labelling.

### Trigger
`POST /api/import/ai-topics`, **one question per request**, admin-only. The browser drives the
fan-out — the import review screen fires one request per question in the paper, staggered by a
client-side rate-limited queue. The same endpoint backs "Re-run AI" in Manage Papers.

The route fetches the question's topic/subtopic list scoped to the paper's `subject_id` +
`stream_id`, downscales the question's page images for the call (`downscale_for_ai`, capped at 768 px
long side), and calls Claude. It returns
`{"parts": [{label, marks, selections: [{topic_id, subtopic_id}]}]}` — the suggested split *and*
labelling — for review. **It persists nothing.**

Upstream failures map to distinct statuses so the UI can say something useful: **429** rate limited,
**503** API unavailable, **502** the response was truncated mid-tool-call. All three are retryable
per question.

### Model
**Claude Haiku 4.5** (`claude-haiku-4-5-20251001`). Vision input required; only the question-type
page images are sent — marks are printed on the question paper, not the answer key.

### Prompt strategy
The system block lists the valid topics/subtopics for the question's (subject, stream) as
**positional codes** — `"1.1"`, `"2"` — not database ids. `_build_options` renders the list and keeps
a `code_map` from code back to `(topic_id, subtopic_id)`, so Claude never sees or invents a DB id,
and any code it returns that isn't in the map is dropped.

Topics that have subtopics show only their subtopic lines (the subtopic is what gets picked); topics
without subtopics show one bare line.

The prompt's load-bearing rules beyond topic selection:

- Split the question into parts exactly as the paper labels them, in printed order.
- **`(a)(i)` and `(a)(ii)` are two separate parts** — a question with `(a)(i)`, `(a)(ii)` and `(b)`
  has exactly three parts. Without this stated explicitly the model groups the roman numerals under
  one `(a)`.
- A question with no lettered parts has exactly one part, with an empty label.
- Never invent a part that isn't printed.
- **Do not sum marks.** Report the marks printed for each part; if a single total is printed for the
  whole question and can't be attributed, put it on the first part and use `null` for the rest —
  that keeps the question's derived total correct so it stays selectable for marks-target
  generation.

### Response schema
Forced tool use (`tool_choice: {type: "tool", name: "label_parts"}`) rather than free-text JSON, so
the shape is guaranteed:

```json
{
  "parts": [
    { "label": "(a)(i)",  "selected_codes": ["1.1"], "marks": 2 },
    { "label": "(a)(ii)", "selected_codes": ["1.2"], "marks": 3 },
    { "label": "(b)",     "selected_codes": ["9"],   "marks": 5 }
  ]
}
```

`max_tokens` is 1500 — a multi-part question emits one object per part.

**A truncated response is an error, not a result.** If `stop_reason` comes back `max_tokens` the tool
input is partial — some parts missing, or none parsed at all — and a question cut off after two of
its four parts would otherwise be saved as a two-part question with nothing to indicate the loss.
`label_question` raises `TruncatedResponseError`, which the route turns into the **502** above.

The backend maps codes back to ids. Selections are de-duplicated **within** a part, not across parts:
two parts of one question may legitimately test the same subtopic. An empty `parts` array on an
*untruncated* response falls back to a single blank part, preserving the every-question-has-a-part
invariant.

### Prompt caching
The valid-topics list is identical for every question in a given (subject, stream) — and a single
paper is always one (subject, stream) — so the same cached system block is reused across every
question in the paper. The block is marked `cache_control: { type: "ephemeral" }`; cache hits are
dramatically cheaper than fresh tokens.

## Filename metadata extraction

**Trigger:** during PDF upload, after the file is received. The backend extracts metadata suggestions
from the filename and returns them with the page images; the frontend pre-fills the metadata
sidebar.

**Model:** **Claude Haiku 4.5** (`claude-haiku-4-5-20251001`), text-only — fast and cheap.

**Prompt:** send the filename string; ask for school name, year, subject, level, exam type and paper
number as JSON. `resolve_metadata` then maps each name to an existing reference-table ID by **exact,
case-insensitive name match** — unmatched fields are left blank for the user to fill.

```json
{
  "school": "Raffles Institution",
  "year": 2024,
  "subject": "Mathematics",
  "level": "Sec 3",
  "exam_type": "EOY",
  "paper_number": "1"
}
```

Any field can be `null` if the filename doesn't contain that information.

## Persisting the review

### `POST /api/import/save-topics`

- Accepts `{paper_id, questions: [{question_id, parts: [{label, marks, topic_assignments}]}]}` — the
  parts the admin confirmed, in printed order.
- Validates all question ids belong to the paper, and — across *every* question, before writing any
  of them — that each topic is in scope for the paper's subject/stream and each subtopic sits under
  its topic. A 422 therefore leaves the whole paper's existing labelling intact.
- Replaces each question's `QuestionPart` rows wholesale via `set_question_parts`; deleting the old
  parts cascades to their `QuestionTopic`/`QuestionSubtopic` rows. `part_order` comes from list
  order. A question sent with no parts gets one blank part.
- `label` is capped at 32 characters by `PartIn`, matching `question_part.label` — an over-long label
  is a 422, never a silently truncated row.

### The shared parts write path

`app/services/question_parts.py` is the **single** implementation of "replace a question's parts,
topics, subtopics and marks". `POST /api/import/save-topics`, `POST /api/papers/{id}/questions` and
`PUT /api/questions/{id}` all go through it, so validation ordering and dedupe semantics can't drift
between them:

- `scoped_topic_ids(db, subject_id, stream_id)` — the topics a question on that paper may use.
- `validate_parts(db, parts, valid_topic_ids)` — pure validation, writes nothing, so a caller can
  check several questions before touching the DB.
- `set_question_parts(db, question_id, parts, valid_topic_ids)` — validates, then deletes and
  re-inserts.

## Review UI

### The review step (`TopicReview.jsx`)

After confirm, the browser fires `POST /api/import/ai-topics` once per question through a
rate-limited queue (`REQUEST_INTERVAL_MS`, staggering request *starts*) and shows per-question
progress with a Re-run/Retry button.

For each question it renders the question image(s) beside a `<PartsEditor />` pre-filled with the
AI's suggested split. The admin can edit any part's label, marks and topics, **add or delete parts**,
then save the whole paper with `POST /api/import/save-topics`. Marks are entered per part — there is
no question-level marks field; the editor shows the running total instead.

### `<PartsEditor />` (`src/components/PartsEditor.jsx`)

The single place a question's parts are edited, used by **both** the import review step and the admin
question editor (`QuestionEditor.jsx`) — the two previously carried near-identical topic-chip +
combobox blocks.

Per part it renders a label input, a marks input, the selected topic chips with remove buttons, and
its own `<TopicCombobox />`; below the list sit "+ Add part" and a live total. Because each part
passes its own `selected` array to the combobox, the same subtopic can be picked on two different
parts while still being de-duplicated within one. Deleting the last part leaves one blank part —
every question has at least one.

Its working shape is `{label, marks, selected: [{topic_id, subtopic_id}]}`.
`src/features/import/topicUtils.js` converts to and from the API: `partsFromApi` (tolerating both the
detail and editor payload shapes, and always returning at least one part), `partsToPayload`, and
`partsTotalMarks` (which returns `null` when no part carries marks, matching the backend's `SUM`).

## Cost estimates

Claude Haiku 4.5 is $1.00 / $5.00 per million input / output tokens; cache writes bill at 1.25×
input and cache reads at 0.1×.

| Call | Model | Input | Volume / year | Cost / year |
|---|---|---|---|---|
| Part splitting + topic labeling | Haiku 4.5 (vision) | ~1 image + cached topic list | ~9,600 questions | ~$10 |
| Filename extraction | Haiku 4.5 (text) | filename string | ~640 papers | negligible (<$1) |

Per-question labeling is roughly $0.001 with image input — order of magnitude, verify against the
logs. `log_tokens` (`app/logger.py`) prints per-call token counts and a dollar cost to
`logs/app.log`.

## SDK setup

- **Library:** `anthropic` (Python).
- **Env var:** `ANTHROPIC_API_KEY` (see [DEPLOYMENT.md](../DEPLOYMENT.md#configuration-reference)).
- **Model IDs:** both calls use `claude-haiku-4-5-20251001`.
- **Where it lives:** `app/ai/` — one client per use case (`topic_labeler.py`,
  `filename_extractor.py`).
- Always enable prompt caching on the topic list block when batching across one paper's questions.
