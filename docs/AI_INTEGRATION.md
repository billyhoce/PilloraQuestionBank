# AI Integration

**Scope:** All Anthropic Claude API usage — invoked from the backend, surfaced through the frontend. For where these calls fit into the import pipeline (server side), see [BACKEND.md](./BACKEND.md). For the part-review UI (step 9 of import), see [FRONTEND.md](./FRONTEND.md).

## Part Splitting & Topic Auto-labeling

One call does both jobs: it splits a question into its printed parts and labels
each part with the topics it tests and the marks it is worth. Images are never
split — a question is one set of page images covering all its parts, so the
split exists only in the labelling. See
[DATA_MODEL.md](./DATA_MODEL.md#questions-have-parts).

### Trigger
`POST /api/import/ai-topics`, **one question per request**, admin-only. The
browser drives the fan-out — the import topic-review screen fires one request
per question in the paper, staggered by a client-side rate-limited queue
(`TopicReview.jsx`). The same endpoint backs "Re-run AI" in Manage Papers.

### Model
**Claude Haiku 4.5** (`claude-haiku-4-5-20251001`). Vision input required; only
the question-type page images are sent (marks are printed on the question
paper, not the answer key).

### Prompt Strategy
The system block lists the valid topics/subtopics for the question's
(subject, stream) as **positional codes** — `"1.1"`, `"2"` — not database ids.
`_build_options` renders the list and keeps a `code_map` from code back to
`(topic_id, subtopic_id)`, so Claude never sees or invents a DB id, and any code
it returns that isn't in the map is dropped.

Topics that have subtopics show only their subtopic lines (the subtopic is what
gets picked); topics without subtopics show one bare line.

The prompt's load-bearing rules, beyond topic selection:

- Split the question into parts exactly as the paper labels them, in printed order.
- **`(a)(i)` and `(a)(ii)` are two separate parts** — a question with `(a)(i)`,
  `(a)(ii)` and `(b)` has exactly three parts. Without this stated explicitly the
  model groups the roman numerals under one `(a)`.
- A question with no lettered parts has exactly one part, with an empty label.
- Never invent a part that isn't printed.
- **Do not sum marks.** Report the marks printed for each part; if a single total
  is printed for the whole question and can't be attributed, put it on the first
  part and use `null` for the rest — that keeps the question's derived total
  correct so it stays selectable for marks-target generation.

### Response Schema
Forced tool use (`tool_choice: {type: "tool", name: "label_parts"}`) rather than
free-text JSON, so the shape is guaranteed:

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

**A truncated response is an error, not a result.** If `stop_reason` comes back
`max_tokens` the tool input is partial — some parts missing, or none parsed at
all — and a question cut off after two of its four parts would otherwise be
saved as a two-part question with nothing to indicate the loss. `label_question`
raises `TruncatedResponseError`, which the route turns into a **502** telling the
admin to retry that question (the review screen already has a per-question retry).

The backend maps the codes back to ids and returns
`{"parts": [{"label", "marks", "selections": [{"topic_id", "subtopic_id"}]}]}`.
Selections are de-duplicated **within** a part, not across parts: two parts of
one question may legitimately test the same subtopic. An empty `parts` array on
an *untruncated* response falls back to a single blank part, preserving the
every-question-has-a-part invariant.

**Nothing is persisted here.** The response is transient; the admin reviews and
corrects it in the UI, and `POST /api/import/save-topics` does the writing.

### Prompt Caching
The valid-topics list is identical for every question in a given (subject, stream) — and a single paper is always one (subject, stream) — so the same cached system block is reused across every question in the paper. The system block is marked `cache_control: { type: "ephemeral" }`. Cache hits are dramatically cheaper than fresh tokens.

## Filename Metadata Extraction

### Trigger
During PDF upload, after the file is received. Backend extracts metadata suggestions from each PDF's filename and returns them to the frontend, which pre-fills the metadata sidebar.

### Model
**Claude Haiku** (`claude-haiku-4-5-20251001`). Text-only — fast and cheap.

### Prompt
Send the filename string. Ask for school name, year, subject, level, exam type, paper number as JSON. The backend (`resolve_metadata`) then maps each name to an existing reference-table ID by **exact, case-insensitive name match** — unmatched fields are left blank for the user to fill.

### Response Schema

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

## Cost Estimates

Claude Haiku 4.5 is $1.00 / $5.00 per million input / output tokens; cache
writes bill at 1.25× input and cache reads at 0.1×.

| Call | Model | Input | Volume / year | Cost / year |
|---|---|---|---|---|
| Part splitting + topic labeling | Haiku 4.5 (vision) | ~1 image + cached topic list | ~9,600 questions | ~$10 |
| Filename extraction | Haiku 4.5 (text) | filename string | ~640 papers | negligible (<$1) |

Per-question labeling is roughly $0.001 with image input on Haiku 4.5 (order of
magnitude — verify against the logs). Prompt caching on the topic list reduces
the marginal cost meaningfully. `log_tokens` (`app/logger.py`) prints per-call
token counts and a dollar cost to `logs/app.log`.

## SDK Setup

- **Library:** `anthropic` (Python).
- **Env var:** `ANTHROPIC_API_KEY` (set in production via Oracle VM env or systemd unit; see [DEPLOYMENT.md](./DEPLOYMENT.md)).
- **Model IDs:**
  - Vision (part splitting + topic labeling): `claude-haiku-4-5-20251001`
  - Text-only (filename): `claude-haiku-4-5-20251001`
- **Where it lives:** `app/ai/` module — one client per use case (`topic_labeler.py`, `filename_extractor.py`).
- Always enable prompt caching on the topic list block when batching across one paper's questions.
