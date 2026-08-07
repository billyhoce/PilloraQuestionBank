# Paper Generation

**Scope:** Turning a filtered selection into a downloadable PDF — the selection algorithms, the two
generate endpoints, and the `/generate` UI. The rendering itself is in
[pdf-rendering.md](./pdf-rendering.md); the admin presets that constrain non-admin generations are in
[generation-config.md](./generation-config.md).

## API — authenticated

```
POST   /api/generate/select      -- auto-select a set of questions for a target.
                                    Body: { filters, target_type, target_value,
                                    exclude_question_ids[], algorithm }. `filters` mirrors
                                    the Browse filter params. `target_type` is "marks"
                                    (target_value = marks total) or "count" (target_value =
                                    number of questions). `algorithm` is "random" (default)
                                    or "in-order". Returns { items, total_marks, count,
                                    exact, warning }.
POST   /api/generate/paper       -- render a PDF from a manual selection.
                                    Body: { question_ids[] (min 1), variant:
                                    "question"|"answer"|"combined", additional_instructions,
                                    header_text, footer_text, include_cover, cover_title,
                                    cover_subtitle1, cover_subtitle2, cover_body }.
                                    additional_instructions, header_text, footer_text and
                                    cover_body are rich-text HTML (app/pdf/rich_text.py).
                                    header_text is nullable: omit it to get the config preset.
                                    Returns application/pdf. Empty question_ids -> 422.
```

Both require authentication (`get_current_user`), not admin.

`/generate/select` (`app/routes/generate.py`) reuses the Browse filter suite (`apply_filters` plus
the eager-load options from `app/services/question_query.py`) to build the candidate pool, excludes any
`exclude_question_ids`, then dispatches on `target_type` + `algorithm`. It **never returns 404** — an
empty result with a `warning` string keeps the live builder UI responsive.

The pool is then narrowed by `restrict_premium_pool` (`app/services/premium.py`): free papers always
survive, but a premium paper only does if the viewer holds **its** school level. This is why the pool
query joins `Paper.level` explicitly rather than reaching it through a `.has()` subquery like the
Browse filters do. `/generate/paper` applies the same rule per question and `403`s on any the viewer
can't open. See [users-and-premium.md](./users-and-premium.md#how-the-paywall-is-enforced).

### Role enforcement on `/generate/paper`

Admins control every field verbatim. For every non-admin user — whatever premium they hold — the admin-set
[generation config](./generation-config.md) wins. `_resolve_generation_options` in
`app/routes/generate.py` applies the rules and returns a `ResolvedGenerationOptions` — a frozen
dataclass rather than a tuple, since four of its fields are strings that all get stamped somewhere
on the PDF and a positional mix-up would swap the header with the footer silently:

- `include_cover` is forced to `true` — users always get a cover page.
- `cover_body`, `additional_instructions`, `header_text` and `footer_text` are replaced with the
  config presets.
- `header_text` is the one nullable field: **admins** may override it per generation, but omitting it
  (`null`) falls back to the config preset, so a client that never loaded the config still gets the
  branding. An explicit `""` — or the `"<p></p>"` the editor stores for a cleared field — is an admin
  opting out of the header.
- `cover_title` must be one of the configured cover titles: an unknown title → `400` (a hand-crafted
  POST can't bypass the dropdown); an empty/omitted title falls back to the **first** configured
  title; with no titles configured the cover is untitled.
- `cover_subtitle1` / `cover_subtitle2` stay free text for everyone.

## Question selection (`app/services/generate.py`)

Selection reads `Question.total_marks` — the derived `SUM(QuestionPart.marks)`, not a stored column
(see [DATA_MODEL.md](../DATA_MODEL.md#questions-have-parts)).

**Marks target.** Both marks selectors ignore questions whose total is `null` or non-positive, and
return `[]` for a non-positive target or when nothing is selectable. A question none of whose parts
carry marks is therefore never picked by a marks target — which is why the AI labeller puts an
unattributable question-level total on the first part rather than leaving every part null.

`knapsack_select(questions, target_marks)` (`algorithm="random"`):

- **Randomized-restart greedy**, not an exact optimizer. Each restart shuffles the pool and greedily
  adds questions until the running total reaches the target, considering every intermediate subset.
  The restart budget scales with pool size (`_RESTARTS_PER_QUESTION = 20`, clamped to `[200, 2000]`).
- Prefers an **exact match**; otherwise returns the subset whose total is closest (a slight overshoot
  is allowed if it lands closer). The randomness is intentional: the same filters and target produce
  a *different* paper each time (equally-good subsets are reservoir-sampled). Stops early on an exact
  match.

`in_order_select(questions, target_marks)` (`algorithm="in-order"`):

- **Deterministic single greedy pass** over the pool in its given (`Question.id`) order that **stops
  at the first question which would exceed the target** — the result never overshoots. No shuffling,
  restarts or tie-break randomness, so the same pool and target always return the same questions from
  the top of the list.

**Count target.** `count_select(questions, count, *, randomize)` selects a fixed *number* of
questions — `random.sample` of `count` when `algorithm="random"`, else the first `count` in id order.
Unlike the marks selectors it does **not** filter out null-mark questions (the caller is choosing a
count, not a marks total). Returns all matches when `count` exceeds the pool size.

**Add-to-selection.** The frontend passes the already-chosen questions in `exclude_question_ids` and
reduces `target_value` by their running total (marks) or count, so autofill tops up an existing
selection instead of replacing it.

## Generate UI

`/generate` (`src/pages/GeneratePage.jsx`), authenticated-only. A single page combining manual
selection and autofill — not separate tabs. Layout: filtered results on the left, a sticky sidebar
(autocreate panel + selection cart) on the right. The sidebar fills the viewport height
(`lg:h-[calc(100vh-3rem)] lg:overflow-y-auto`) and scrolls as a single region, so a long cart scrolls
the sidebar rather than the page.

### Filtered results (left)

- Reuses the Browse `<FilterBar />` and `<QuestionCard />` (in `selectable` mode) plus paginated
  "Load more". Each card shows an `+ Add` / `✓ Added` toggle and the question's marks; clicking the
  preview opens the shared `<QuestionDetailModal />`.
- **Select All** (in the results header) adds up to **`SELECT_ALL_LIMIT` = 50** questions matching
  the current filters to the cart (merged/de-duped). It refetches page 1 via `api.questions.list`;
  when the filter's `total` exceeds 50 it adds the first 50 and warns (the button label also reads
  "Select All (first 50)").

### Manual selection cart (right)

Adding/removing maintains a cart of full list-item objects, de-duped by id. It lists each question
(school / year / Q-number, marks) with a remove button, a running **total marks**, and a warning when
any selected question has no marks set. "Clear" empties it.

### Autocreate panel (right)

A **"Select by"** dropdown — **Number of questions** (default) or **Marks** — plus a number input
whose label follows the choice, a **Replace selection / Add to selection** radio, and a **Picking
Algorithm** radio (**In-order / Random**) with an `<InfoTooltip />` explaining the difference. The
panel defaults to **Random + Number of questions**.

"Autocreate Paper" calls `POST /api/generate/select`:

- **Replace** — sends the raw target; the response items become the new cart.
- **Add** — sends `target_value - cartTotalMarks` (marks) or `target_value - cart.length` (count) and
  the current cart ids as `exclude_question_ids`, guarding against a non-positive remaining target.
- For a marks target, In-order stops just before exceeding the total and Random gets as close as it
  can; for a count target, In-order takes the first N and Random takes N at random.

It surfaces the server's `warning` (inexact total, too few matches, no matches) or a success summary
as an inline notice.

### Generate PDF (right)

The cover / instructions / header / footer controls are **role-aware** (`useAuth()`), driven by the
config fetched once from `GET /api/generation-config`:

- **Non-admin users** always generate with a cover page (no checkbox). They pick the **title** from a
  `<select>` of the configured cover titles (defaults to the first; disabled when the list is empty)
  and may fill the free-text **subtitle 1 / subtitle 2** inputs, whose grey placeholder text comes
  from the config. There is **no** body editor, instructions, header or footer control — the server
  stamps the config presets, which they first see in the download. Their request carries only
  `question_ids, variant, cover_title, cover_subtitle1, cover_subtitle2`.
- **Admins** keep the full controls: an **"Include cover page"** checkbox (on by default), a title
  `<select>` plus a **"Custom…"** option revealing a free-text input, the subtitle inputs, the
  **letter body**, an optional **additional instructions** block printed on the first page of the
  question PDF, an optional multi-line **header**, and a **footer** — the last four all in the same
  rich-text editor (`RichTextEditor`, TipTap v3, prefilled from the config and editable
  per-generation without changing the config). The editor is deliberately limited to what the PDF
  renderer supports — paragraphs plus **bold / italic / underline / link** (a small toolbar; link
  URLs via prompt); headings and lists are disabled. All four are sent as HTML and sanitized
  server-side.
- If the config fetch fails, the fields are omitted from the request so the server-side presets (and
  the first-title fallback) still apply. Cover fields are sent on **every** call: both covers show
  the same title and subtitles, and the renderer appends `" - Question Paper"` / `" - Answer Key"` to
  the title and draws the letter body on the question cover only. The cover's marks box is filled
  server-side from the selected questions' total.

A **"Download as"** radio chooses the output mode, defaulting to **1 combined PDF**:

- **Combined (default):** one call with `variant: "combined"` — question paper first, answer paper
  appended behind it, downloaded as the `Paper` type.
- **Separate:** calls `api.generate.paper` **twice in parallel** — `variant: "question"` (with
  `additional_instructions`) and `variant: "answer"` — downloaded as the `Questions` and `Answers`
  types, with a short gap between the two so browsers don't drop the second download.

Each call returns a PDF `Blob` (a binary fetch bypassing the JSON-only `request` helper) and
auto-downloads via a local `downloadBlob` helper. The **Generate PDF** button enables once the cart
is non-empty; an **estimated progress bar** (client-side only, no backend streaming) eases toward
~90% while requests are in flight then snaps to 100%. Errors surface as an inline notice.

### Download filenames

`buildPdfFilename` (`src/utils/pdfFilename.js`, covered by `pdfFilename.test.js`) builds names from
the worksheet **Title** — the cover title the user entered (`coverTitle` in `GeneratePage.jsx`):

```
Pillora_<Title>_<Type>.pdf
```

- `<Type>` is `Ques and Ans` (combined), `Questions`, or `Answers`.
- Only the Title is used — no filters, topics or subtitles. It is trimmed and stripped of
  filesystem-invalid characters (`\ / : * ? " < > |`).
- A Title is **always** present: when the field is blank (or not yet loaded) it falls back to the
  seeded cover title (`DEFAULT_COVER_TITLE`, `Topical Worksheets`), so the filename matches the title
  stamped on the cover.
