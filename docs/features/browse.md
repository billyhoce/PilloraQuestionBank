# Browse & Filter

The public question bank at `/`: anyone (signed in or not) filters and searches questions, sees their
metadata, and opens a detail view. Premium papers' images are shown only to entitled viewers. The
Generate page reuses the same filters and result cards ([paper-generation.md](./paper-generation.md)).

**Code:** `app/routes/questions.py`, `app/services/question_query.py`,
`app/services/question_serialization.py`, `app/services/premium.py`,
`frontend/src/pages/BrowsePage.jsx`, `frontend/src/components/browse/`,
`frontend/src/hooks/useQuestionSearch.js`, `frontend/src/utils/premium.js`
**Related:** [users-and-premium.md](./users-and-premium.md), [site-config.md](./site-config.md),
[reference-data.md](./reference-data.md)

## Filters

All optional and combinable; Browse keeps them in the URL so a filtered view can be shared or
bookmarked. Any change refetches from page 1.

| Filter | Control | Rule |
|---|---|---|
| Level | chips (labelled with school level, e.g. "Secondary 3") | exact |
| Stream | chips | exact; only streams of the chosen level's school level are offered |
| Subject | chips | exact |
| Topic | chips, multi-select | only once **both Subject and Stream** are chosen; matches when **any part** of the question carries a selected topic |
| Exclusive only | checkbox beside topics | question's topics (across all parts) must be a **subset** of the selection; disabled until a topic is chosen, cleared when topics are emptied |
| Tags | tag picker, multi-select | question carries any selected tag |
| School | dropdown | exact |
| Year | dropdown of years that exist for the chosen subject/stream/level, newest first | exact |
| Exam type | dropdown | exact |
| Paper no. | free text | exact, case-insensitive; values may contain letters (`1`, `a`) |
| Search | free text | see below |

- Picking a level whose school level differs from the chosen stream clears the stream, and vice versa.
- Changing subject or stream clears the topic selection and Exclusive only.

### Search

- Runs **live**, ~300 ms after the last keystroke; Enter or **Search** commits at once; **Clear**
  returns to all questions.
- Case-insensitive substring match against **any** of: topic, subtopic, tag, school, subject, level,
  stream and exam-type names, and the school level of the level or stream (e.g. "Secondary").
- `T{n}` (e.g. `T10`) also matches topic number *n*.
- An all-digit keyword also matches the paper year exactly.

## Results

- Ordered by question id, 50 per page, with **Load more** and a "Showing X of Y" count.
- Each card: first question page as thumbnail, topic chips (union across all parts, de-duplicated),
  title `School Year ExamType PaperNo · Q{n}`, subtopic names, tags.
- **Detail view** is a modal over the page (no separate URL): all question and answer pages, marks
  (sum of parts), subtopics, tags, and a **Breakdown** of each part's label, marks and topics. The
  breakdown is hidden for a question that is a single unlabelled part.
- Admins can add/remove tags on a question directly in the detail modal.

## Premium visibility

| Viewer | Non-premium paper | Premium paper |
|---|---|---|
| Anonymous / Normal | metadata + images | metadata only (locked) |
| Premium for the paper's school level | metadata + images | metadata + images |
| Admin | metadata + images | metadata + images |

- A paper's school level is the one on its **level** ([users-and-premium.md](./users-and-premium.md)).
- Locked questions still appear in results as teasers: image URLs are withheld server-side, the card
  shows a premium placeholder naming the school level needed (e.g. "requires Secondary premium"),
  and the detail modal shows a **Get {School level} Premium** link to `/subscribe` with that plan
  highlighted. Metadata, topics, parts and marks stay visible.
- Every displayed question image honours the site-wide copy deterrent (no right-click, drag or
  long-press menu for non-admins when enabled) — see [site-config.md](./site-config.md).
