# Browse & Filter

**Scope:** The public read surface — `GET /api/questions`, `GET /api/questions/:id`, and the filter
/ results UI on `/` and `/questions/:id`. The Generate page reuses this filter suite; see
[paper-generation.md](./paper-generation.md).

## API — public read

```
GET    /api/questions             -- filter params: subject_id, stream_id, level_id, year,
                                     school_id, exam_type_id, topic_ids[] (repeatable),
                                     exclusive (bool — restrict to only the given topics),
                                     paper_number (case-insensitive exact match; strings may
                                     contain letters, e.g. "1", "a"),
                                     search (free-text keyword, OR-matched case-insensitively
                                     against topic, subtopic, tag, school, subject, level,
                                     school-level tier (e.g. "Secondary"), stream and exam-type
                                     names; a "T{n}" token (e.g. "T10") matches the topic
                                     number; an all-digit keyword also matches the paper year
                                     exactly),
                                     page, page_size
                                  -- returns paginated question list with paper info, topic chips
                                     ({ topic_name, topic_number, subtopic_names[] }),
                                     marks (summed across the question's parts), and a
                                     presigned first-page image URL
GET    /api/questions/:id         -- full question detail: question pages + answer pages
                                     (each with a presigned S3 URL), topics, and parts
                                     ({ part_order, label, marks, topics[] })
```

`_apply_filters` in `app/routes/questions.py` builds the query; `POST /api/generate/select` reuses it
plus the same eager-load options.

### Topics are per part; the list endpoint returns their union

`topics` on a list item is the de-duplicated union of every part's topics, with subtopic names
merged — so a browse card renders exactly as it did before questions had parts. The per-part
breakdown is only on the detail endpoint, keeping the list payload small (the list query still loads
parts to build the union, it just doesn't serialize them).

`topic_ids` matches when **any** part carries a selected topic. `exclusive` means **no** part carries
a topic outside the selection — i.e. the union of the question's topics is a subset of the selection,
the same meaning it had when topics were recorded at question level.

### Access

Both endpoints take optional auth so they stay public but can withhold image URLs from premium
papers. See [users-and-premium.md](./users-and-premium.md#how-the-paywall-is-enforced).

## Filter panel UI

All filters are optional and combinable.

- **Subject** — single-select dropdown
- **Stream** — single-select dropdown
- **Level** — single-select dropdown
- **Year** — single-select dropdown OR range
- **School** — multi-select
- **Exam Type** — multi-select
- **Paper Number** — free-text, case-insensitive exact match (values may contain letters)
- **Topic** — multi-select, **scoped to the selected Subject + Stream** (greyed out until both are
  chosen), rendered by `TopicMultiSelect.jsx` (reused by Browse and Generate).
  - **Exclusive only** — a checkbox beside the topic chips restricting results to questions covering
    **only** the selected topics (maps to the `exclusive` param). Disabled until at least one topic
    is selected, auto-cleared when the selection is emptied. A help "?" badge (the shared
    `InfoTooltip.jsx`) shows an explanation on hover, pins it open on click, and dismisses on
    outside-click / Escape / scroll; it is portal-rendered so the filter card can't clip it.
- **Subtopic** — multi-select, **scoped to the selected Topic(s)**
- **Search** — free-text box running **live as the user types**, debounced ~300 ms after the last
  keystroke (Enter or the Search button commit instantly); clearing it returns to all questions.

## Results view

- A grid of matching questions, each card showing: first-page thumbnail, paper-local question number,
  paper info (school / year / level / exam type), marks (summed across parts), and topic chips (the
  union across parts).
- **Click to expand** — `QuestionDetailModal.jsx` shows all pages plus a **Breakdown** section
  listing each part's label, marks and topics. The breakdown is hidden for a question that is a
  single unlabelled part, where it would only repeat the topic chips above it.
- Pagination or infinite scroll.
