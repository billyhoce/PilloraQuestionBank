# Site Config — About page & image protection

**Scope:** The two site-wide settings held in the `site_config` singleton — the public About page's
rich-text body, and the toggle that discourages copying question images — plus the editor and the
`ProtectedImage` component they drive. Generation presets are a different singleton, in
[generation-config.md](./generation-config.md).

`SiteConfig` is a **single row** (`ck_site_config_singleton` enforces `id = 1`), deliberately
separate from `GenerationConfig`:

- that table is scoped to paper-generation presets, and
- `GET /api/generation-config` requires authentication, while **both** settings here must reach
  signed-out visitors — `/about` is public and so is the Browse page that reads the image flag.

Defaults live in `app/services/site_config.py` (`DEFAULT_ABOUT_CONTENT`); `get_or_create_site_config`
lazily re-creates the row if missing, so the app self-heals on an unseeded database. Migration
`d5e6f7a8b9c0` creates and seeds the table. Field shapes are in
[DATA_MODEL.md](../DATA_MODEL.md#core-tables).

## API

Router: `app/routes/site_config.py`; service: `app/services/site_config.py`.

```
GET  /api/site-config   -- PUBLIC, no auth dependency at all. Returns
                           { about_content, protect_images }. Neither value is
                           secret — the About copy is printed on a public page and
                           the flag only changes how images are rendered.

PUT  /api/site-config   -- admin. Body { about_content?, protect_images? }.
                           A **partial** update: only the fields present are written.
                           about_content is sanitized here (see below) and the
                           sanitized HTML is what comes back.
```

**Why partial and not a full replace.** The two settings are edited from different screens — the
About body from `/about`, the image toggle from User Management. A full replace would let whichever
page saved last overwrite the other's value with whatever it happened to have loaded.

## Sanitizing the About content

This is the **only** place the app renders stored HTML into the browser
(`dangerouslySetInnerHTML` in `AboutPage.jsx`), so the allowlist is the security boundary.

- Sanitized **on write**, in `sanitize_about_content` (`app/services/site_config.py`), using
  `bleach[css]`. Doing it on write keeps the stored value clean for every future consumer and means
  no frontend sanitizer to keep in sync — there is no DOMPurify in the bundle.
- Allowlist: `p br hr strong b em i u s sub sup h1–h4 ul ol li blockquote a span div`;
  attributes `a[href title target rel]` and `style` on the block/inline containers.
- `style` is filtered by a `CSSSanitizer` down to `color`, `background-color`, `font-size`,
  `font-family`, `font-weight`, `font-style`, `text-align`, `text-decoration`. A stored
  `position: fixed` would otherwise let one saved page cover the whole app.
- Link protocols are limited to `http`, `https`, `mailto`, so `javascript:` hrefs lose the link and
  keep the text.
- `<script>` and `<style>` elements are dropped **whole** before the clean. bleach strips a
  disallowed tag but keeps its text, which would otherwise dump a stylesheet onto the page as visible
  prose — the usual result of pasting from Word.

Only admins can write this field; the sanitizer is there so a compromised admin session cannot become
stored XSS against every visitor, including signed-out ones.

**This is not the PDF sanitizer.** `app/pdf/rich_text.py` targets ReportLab and supports a much
narrower subset (no headings, lists or colour). The two are independent on purpose — see below.

## The About page

`/about` (`pages/AboutPage.jsx`, nav link **About**) sits inside `<AppShell />` but **outside**
`ProtectedRoute`, like `/`. Signed-out visitors read it; admins get an **Edit page** button that
swaps the rendered body for the editor, with Save / Cancel and an inline notice.

Editing happens **in place** rather than on a separate admin page: the editor surface and the
rendered page share the `.rich-content` class (`src/index.css`), so what the admin sees while typing
is what visitors get. Save stores the **server's response**, not the draft, so anything the sanitizer
stripped disappears immediately instead of lingering until the next reload. The draft is seeded when
editing starts rather than synced by an effect, so a refetch can never clobber unsaved typing.

### `RichContentEditor` vs `RichTextEditor`

Two TipTap editors, deliberately:

| | `components/RichContentEditor.jsx` | `components/generate/RichTextEditor.jsx` |
|---|---|---|
| Used by | About page | Generation Config, Generate form |
| Rendered by | the browser | ReportLab (`app/pdf/rich_text.py`) |
| Marks | bold, italic, underline, strike, H1–H3, bullet/numbered lists, font family, font size, colour, link | bold, italic, underline, link only |
| Bounded by | `app/services/site_config.py` allowlist | `app/pdf/rich_text.py` |

`RichTextEditor` is cut down to what the PDF renderer can draw. **Widening it would let an admin
author headings and lists that the PDF silently strips**, which is why the About page got its own
component instead. `RichContentEditor` adds `@tiptap/extension-text-style`'s `TextStyleKit` for
colour / font family / font size on top of the full `StarterKit`.

`.rich-content` in `src/index.css` is **required, not decorative**: Tailwind's preflight resets list
markers and heading sizes, so without it a bulleted list renders as plain paragraphs in both the
editor and the page.

## Image-download protection

`protect_images` turns on a **client-side deterrent** wherever question images are shown to ordinary
users.

> **It is a deterrent, not protection.** Images reach the browser as presigned S3 URLs embedded in
> the JSON response ([ARCHITECTURE.md](../ARCHITECTURE.md#cross-cutting-conventions)), so anyone who
> opens the Network tab can still fetch the file. What it stops is how casual copying actually
> happens: right-click → Save Image, drag-to-desktop, and the iOS long-press sheet. Do not build
> server-side complexity on the assumption that this is airtight — the real access control is the
> premium paywall, which withholds the URL entirely.

`components/ProtectedImage.jsx` is a drop-in for `<img>`:

- **Off, or the viewer is an admin** → a plain `<img>` with the props passed through. Admins are
  exempt because they need to save and inspect images while importing and editing papers.
- **On** → `draggable={false}`, the `.protected-image` class (`user-select: none` and
  `-webkit-touch-callout: none`, which suppresses the iOS "Save Image" sheet), a wrapper that
  `preventDefault`s `contextmenu` and `dragstart`, and a **transparent overlay** span across the
  image so a right-click or long-press lands on an empty element. The overlay is an empty span rather
  than a transparent PNG: same effect for the events that matter, no extra request.
- The overlay must **not** set `pointer-events: none` (it needs the events) and must stay inside
  whatever button wraps it, so plain clicks still bubble to the card's own `onClick` —
  `QuestionCard` nests the preview in a `<button>`, and swallowing that click would break opening a
  question whenever the toggle is on. `ProtectedImage.test.jsx` pins this.
- Both contexts are read defensively (`useAuth() ?? {}`), since cards are rendered in tests without
  any provider mounted.

**Applied at three sites**, which is every user-facing image: `components/browse/QuestionCard.jsx`
(the card thumbnail) and `components/browse/QuestionDetailModal.jsx` (question and answer pages).
Those two components are shared by Browse *and* Generate, so three edits cover all of it. The
`premium-locked.svg` placeholders and every admin surface (`features/import/*`, `features/papers/*`)
are left alone.

The toggle lives in a **Site settings** panel on User Management (`features/users/UsersList.jsx`) —
see [users-and-premium.md](./users-and-premium.md).

## Frontend plumbing

`context/SiteConfigContext.jsx` fetches `GET /api/site-config` **once** on mount and exposes
`{ aboutContent, protectImages, loading, setConfig, refresh }`. It is mounted inside `AuthProvider`
in `App.jsx`. One shared fetch on purpose: every question image reads `protectImages`, so the
per-page fetching that `/api/generation-config` still uses would mean repeated requests per
navigation. A failed fetch falls back to empty copy and protection **off** rather than blanking the
page. `useSiteConfig()` returns safe defaults when no provider is mounted.

API client: `api.siteConfig.get()` / `api.siteConfig.update(body)` in `src/api/client.js`.
