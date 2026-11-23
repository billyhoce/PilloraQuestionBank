# Manage Papers

Admins list, edit and delete papers already in the bank: metadata, premium flag, questions, page
images, parts/topics/marks and tags.

**Code:** `app/routes/papers.py`, `app/services/paper_admin.py`, `app/services/ingest.py` (paper
delete), `frontend/src/features/papers/` (`PapersList.jsx`, `PaperEditor.jsx`,
`PaperMetadataBar.jsx`, `QuestionEditor.jsx`, `PageImageEditor.jsx`), `frontend/src/components/PartsEditor.jsx`
**Related:** [ai-labelling.md](./ai-labelling.md), [users-and-premium.md](./users-and-premium.md),
[reference-data.md](./reference-data.md), [auto-import.md](./auto-import.md),
[manual-import.md](./manual-import.md), [DATA_MODEL.md](../DATA_MODEL.md)

## Rules

- Admin-only.
- Every metadata field is required; the stream and level must belong to the same school level.
- Question numbers are positive whole numbers, unique within a paper.
- A question has no marks of its own: its total is the sum of its parts' marks
  ([ai-labelling.md](./ai-labelling.md)).
- Image changes are all-or-nothing with the database: new images reach permanent storage before the
  commit; replaced, removed and temporary images are deleted only after it.

## Papers list

`/admin/papers`

- The **200 most recent** papers, newest first: subject, stream, level, school, exam, year, paper,
  question count, and a **Premium** checkbox.
- **Premium** toggles immediately, reverting with an error if the save fails
  ([users-and-premium.md](./users-and-premium.md)).
- **Edit** opens the paper editor; **Delete** asks first.
- **+ Import paper** goes to `/admin/import`.

## Paper editor

`/admin/papers/:id`

**Metadata bar**
- Subject, stream, level, school, exam type, year, paper number and **Premium paper**; **Save
  metadata** is enabled once all are filled.
- **Changing subject or stream** asks first ("Clear topics & save"): topics are scoped to subject and
  stream, so every topic and subtopic on the paper's parts is cleared. Parts and their marks survive.
  Claude then re-labels each question in turn and the editors show its suggestions; they are kept
  only when the admin saves. A question whose re-label fails keeps its own parts.

**Question cards** (sorted by number; a side index jumps to each)
- **Q#** field.
- **Question pages** and **Answer pages:** add an image (**+ Add page**, any image file, standardised
  like an imported page), drag to reorder, × to remove (asks first), click to enlarge.
- **Parts editor:** each part's label, marks, topics and subtopics
  ([ai-labelling.md](./ai-labelling.md)).
- **Re-run AI** replaces the card's parts with fresh Claude suggestions; nothing is stored until Save.
- **Tags:** add from the tag list, remove with ×.
- **Save** writes the card's number, pages, parts and tags together. **Delete** removes the question
  and its images (asks first).
- **+ Add question** adds a draft card numbered after the highest; **Add question** saves it,
  **Cancel** drops it.
- **Save all** saves every card in turn and reports how many failed; failed cards show their error.

## Deleting a paper

- Removes the paper with its questions, pages, parts, topics, subtopics and tags. Images are deleted
  after the commit.
- If the paper came from an auto-import job, a `paper_deleted` event is recorded on that job. The job
  itself is unchanged.
- The Manual import's **Cancel import** at the topic-review step uses the same delete.

## Provenance

Content confirmed from an auto-import job records where it came from. Manual imports and pages added
in the editor leave these empty.

| On | Records |
|---|---|
| Paper | The ingest job that created it |
| Question | The proposal paper's label (`q1`, or `a1` for answers), and its position in that paper's question list |
| Page | The booklet page it was cropped from and the rectangle (PDF points) |

- Answer pages attached from another job carry that job's page and rectangle.
- Provenance is not shown in the editor. To find a paper's job, search its paper id in **All jobs**
  on the [Auto import](./auto-import.md) page.
- Settling a job deletes only its working files; the paper and its provenance stay.
