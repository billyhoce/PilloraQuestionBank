# Reference Data

**Scope:** The admin-curated lookup tables every paper and question is classified against — subjects,
streams, levels, schools, exam types, topics/subtopics — plus their CRUD API and admin UI. Table
shapes are in [DATA_MODEL.md](../DATA_MODEL.md#reference-tables-admin-crud). Cover titles are
reference data too, but they belong to [generation-config.md](./generation-config.md).

## API — admin write, public read

```
GET|POST|PUT|DELETE  /api/school-levels
GET|POST|PUT|DELETE  /api/subjects
GET|POST|PUT|DELETE  /api/streams
GET|POST|PUT|DELETE  /api/levels
GET|POST|PUT|DELETE  /api/schools
GET|POST|PUT|DELETE  /api/exam-types
GET|POST|PUT|DELETE  /api/topics          -- filtered by ?subject_id=&stream_id=; list includes
                                             nested subtopics
GET|POST|PUT|DELETE  /api/subtopics       -- filtered by ?topic_id=
GET                  /api/papers/years    -- distinct paper years, filtered by
                                             ?subject_id=&stream_id=&level_id=
```

Delete endpoints guard against deleting a row that still has dependent data, returning `409` instead
of violating a FK constraint.

Reference data is seeded by the `seed_reference_data` Alembic migration — there is no separate seed
command.

## Topics are scoped to (Subject, Stream)

Topics belong to a **(Subject, Stream)** pair, so the same subject can carry a different topic list
per stream — "G2 Math" and "G3 Math" each define their own topics under `Subject = "Math"`. Topic
names need only be unique within a `(subject, stream)`, so "Algebra" can exist independently under
both.

Two consequences ripple outward:

- The Browse/Generate topic filter is greyed out until both Subject and Stream are chosen.
- Changing a paper's subject or stream clears its questions' topic labels, since they are now
  out of scope. See [ingestion.md](./ingestion.md#editing-an-imported-paper).

## Admin UI

`/admin/reference` — a list / create / edit / delete surface for each of Subjects, Streams, Levels
(with `sort_order`), Schools, Exam Types, and Topics (scoped to a Subject + Stream; includes
`topic_number` and a nested editor for Subtopics).

Built from a shared CRUD stack — `SimpleTab` + `ReferenceTable` + `SimpleNameModal` +
`ConfirmDialog` — which the Generation Config page reuses for cover titles.

The Topics tab shows `topic_number` in its own editable column, rather than as the `T{n}:` prefix
used everywhere else (see [ARCHITECTURE.md](../ARCHITECTURE.md#cross-cutting-conventions)).
