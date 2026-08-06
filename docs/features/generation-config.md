# Generation Config

**Scope:** The admin-set presets and cover-title list that drive every non-admin paper generation and
pre-fill the Generate form. How they are *enforced* at generation time is in
[paper-generation.md](./paper-generation.md#role-enforcement-on-generatepaper); how they are *drawn*
is in [pdf-rendering.md](./pdf-rendering.md).

`GenerationConfig` is a **single row** (`ck_generation_config_singleton` enforces `id = 1`);
`CoverTitle` is the admin-curated list of titles non-admins must pick from. The Alembic migration
seeds the row with canonical defaults and one title, `"Topical Worksheets"`. Those defaults live in
`app/services/generation_config.py` (`DEFAULT_COVER_TITLE`, `DEFAULT_COVER_BODY`,
`DEFAULT_HEADER_TEXT`) and `get_or_create_config` lazily re-creates the row if missing, so the app
self-heals on an unseeded database. Field shapes are in
[DATA_MODEL.md](../DATA_MODEL.md#core-tables).

## API

Router: `app/routes/generation_config.py`; service: `app/services/generation_config.py`.

```
GET    /api/generation-config    -- any authenticated user. Returns { titles: [{id, name}] (id
                                    order — the first is the non-admin dropdown default),
                                    subtitle1_placeholder, subtitle2_placeholder, cover_body,
                                    header_text, additional_instructions, footer_text }.
                                    Nothing here is secret (every value is printed in the PDFs
                                    users generate); writes are what's restricted.
PUT    /api/generation-config    -- admin. Replaces the five preset fields; returns the GET shape.
                                    cover_body / header_text / additional_instructions /
                                    footer_text are rich-text HTML, stored as-is and sanitized at
                                    render time (app/pdf/rich_text.py), same as the request path.
GET    /api/cover-titles         -- any authenticated user. { data: [{id, name}] } in id order.
POST   /api/cover-titles         -- admin. Body { name }. Duplicate -> 409. Returns 201.
PUT    /api/cover-titles/:id     -- admin. Body { name }. Duplicate -> 409, unknown id -> 404.
DELETE /api/cover-titles/:id     -- admin. Plain delete (nothing references titles). 204.
```

Serving the live config is what lets the frontend pre-fill the editable fields without keeping its
own copy of the defaults.

## Admin UI

`/admin/generation-config` (`GenerationConfigPage.jsx`, nav link **Generation Config**):

- **Cover Titles** — list / add / edit / delete via the shared reference CRUD stack (`SimpleTab` +
  `ReferenceTable` + `SimpleNameModal` + `ConfirmDialog`), wired to `api.coverTitles`. Users
  generating a paper must pick from this list (the first entry is the dropdown default); admins can
  also type a custom title during generation.
- **Generation Presets** form — **subtitle 1 / subtitle 2 placeholders** (the grey hint text in the
  Generate form) as plain inputs, then four **rich-text editors** (the same `RichTextEditor` the
  Generate page uses): the **cover body**, the **header** (branding drawn right-aligned on the top
  rule of every page — multi-line, stacking upward from the rule), the **additional instructions**
  (below the top rule on the question paper), and the **footer** (bottom-left of every page). All
  four support **bold / italic / underline / link**, and links print blue and stay clickable in the
  PDF. Saved via `PUT /api/generation-config` (`api.generationConfig.update`) with an inline
  success/error notice.
