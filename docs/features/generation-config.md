# Generation Config

Admin-set presets and the cover-title list that govern every non-admin paper generation and pre-fill
the admin's Generate form. Edited at `/admin/generation-config` (nav: **Generation Config**).

**Code:** `app/routes/generation_config.py`, `app/services/generation_config.py`,
`frontend/src/pages/admin/GenerationConfigPage.jsx`, `frontend/src/components/generate/RichTextEditor.jsx`
**Related:** [paper-generation.md](./paper-generation.md) (how presets are enforced),
[pdf-rendering.md](./pdf-rendering.md) (how they are drawn), [DATA_MODEL.md](../DATA_MODEL.md)

## What is configured

| Setting | Type | Used for |
|---|---|---|
| **Cover titles** | list of names | non-admins must pick one; the **first** (oldest) is the default |
| Subtitle 1 / 2 placeholder | plain text | grey hint text in the Generate form's subtitle inputs |
| Cover body | rich text | the letter on the question paper's cover |
| Header | rich text | branding right-aligned on the top rule of every page; multi-line, stacking upward |
| Additional instructions | rich text | band below the top rule on the question paper's first page |
| Footer | rich text | bottom-left of every page |

- Rich text = paragraphs with **bold / italic / underline / link**; links print blue and stay
  clickable in the PDF. Values are stored as entered and sanitized when a PDF is rendered.
- There is exactly one config. A fresh database is seeded with defaults — the Pillora letter body,
  the Pillora website/Telegram header, placeholder hints, blank instructions and footer — and one
  title, **Topical Worksheets**. If the config is ever missing it is recreated with those defaults (titles are not
re-seeded).

## Rules

- **Read:** any signed-in user (every value is printed on the PDFs they generate, so nothing is
  secret). **Write:** admins only.
- Saving the presets replaces all six preset fields at once.
- Cover-title names are unique; adding or renaming to an existing name is rejected. Deleting a title
  is unrestricted — PDFs already generated keep the text.
- With no titles configured, non-admin covers are untitled and admins default to a custom title.
- Admins can still override any preset per generation and type a custom title; non-admins cannot
  ([paper-generation.md](./paper-generation.md#cover-header-and-footer-controls)).

## Admin page

- **Cover Titles** — list / add / edit / delete, same table-and-modal pattern as reference data.
- **Generation Presets** — the two placeholder inputs, then four rich-text editors (cover body,
  header, additional instructions, footer), saved together with an inline success/error notice.
