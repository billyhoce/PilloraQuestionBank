# AI Integration

**Scope:** All Anthropic Claude API usage — invoked from the backend, surfaced through the frontend. For where these calls fit into the import pipeline (server side), see [BACKEND.md](./BACKEND.md). For the topic-review UI (step 9 of import), see [FRONTEND.md](./FRONTEND.md).

## Topic Auto-labeling

### Trigger
After import confirmation. Frontend calls `POST /api/import/ai-topics`; backend iterates the paper's questions and calls Claude per question.

### Model
**Claude Sonnet** (latest — `claude-sonnet-4-6`). Vision input required.

### Prompt Strategy
Send the question's page image(s) to Claude alongside the **list of valid topics/subtopics for the question's (subject, stream)**. Ask for JSON only.

```
System:
You are a topic classifier for {subject} ({stream}) exam questions.
Valid topics: [
  { id: 1, name: "Algebra", subtopics: [
      { id: 11, name: "Linear equations" },
      { id: 12, name: "Quadratic equations" }
  ]},
  ...
]
Respond with JSON only:
{ "topics": [{ "topic_id": int, "subtopic_id": int|null }] }

User:
[image(s) of the question]
Classify this question into one or more topics from the list above.
```

### Response Schema

```json
{
  "topics": [
    { "topic_id": 1, "subtopic_id": 11 },
    { "topic_id": 3, "subtopic_id": 1 }
  ]
}
```

The backend stages these in `QuestionTopic` (or holds them pending) so the user can review and correct in the frontend's topic-review screen.

### Prompt Caching
The valid-topics list is identical for every question in a given (subject, stream) — and a single paper is always one (subject, stream) — so the same cached system block is reused across every question in the paper. Use Anthropic's **prompt caching** (mark the system block with `cache_control: { type: "ephemeral" }`). Cache hits are dramatically cheaper than fresh tokens.

## Filename Metadata Extraction

### Trigger
During PDF upload, after the file is received. Backend extracts metadata suggestions from each PDF's filename and returns them to the frontend, which pre-fills the metadata sidebar.

### Model
**Claude Haiku** (`claude-haiku-4-5-20251001`). Text-only — fast and cheap.

### Prompt
Send the filename string. Ask for school name, year, subject, level, exam type, paper number as JSON. The backend then maps each name to an existing reference-table ID where possible (best-effort fuzzy match — leave unmatched fields blank for the user to fill).

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

| Call | Model | Input | Volume / year | Cost / year |
|---|---|---|---|---|
| Topic labeling | Sonnet (vision) | ~1 image + cached topic list | ~9,600 questions | ~$48 |
| Filename extraction | Haiku (text) | filename string | ~640 papers | negligible (<$1) |

Per-question topic labeling is approximately $0.005 with image input on Sonnet (current pricing — verify before launch). Prompt caching on the topic list reduces the marginal cost meaningfully.

## SDK Setup

- **Library:** `anthropic` (Python).
- **Env var:** `ANTHROPIC_API_KEY` (set in production via Oracle VM env or systemd unit; see [DEPLOYMENT.md](./DEPLOYMENT.md)).
- **Model IDs:**
  - Vision (topic labeling): `claude-sonnet-4-6`
  - Text-only (filename): `claude-haiku-4-5-20251001`
- **Where it lives:** `app/ai/` module — one client per use case (`topic_labeler.py`, `filename_extractor.py`).
- Always enable prompt caching on the topic list block when batching across one paper's questions.
