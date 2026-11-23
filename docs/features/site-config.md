# Site Config — About page & image-copy deterrent

Two site-wide settings: the public **About page** body (rich text, edited in place by admins) and the
**Discourage copying of question images** toggle. Generation presets are a separate setting, in
[generation-config.md](./generation-config.md).

**Code:** `app/routes/site_config.py`, `app/services/site_config.py`,
`frontend/src/context/SiteConfigContext.jsx`, `frontend/src/pages/AboutPage.jsx`,
`frontend/src/components/RichContentEditor.jsx`, `frontend/src/components/ProtectedImage.jsx`,
`frontend/src/features/users/UsersList.jsx`
**Related:** [users-and-premium.md](./users-and-premium.md), [pdf-rendering.md](./pdf-rendering.md),
[DATA_MODEL.md](../DATA_MODEL.md)

## Rules

- Both settings are **readable by anyone**, signed in or not: `/about` is public, and so is Browse,
  which needs the image flag.
- Only admins change them.
- Saves are **partial**: the About editor saves only the body and the toggle saves only the flag, so
  the two screens can't overwrite each other.
- Defaults: a short placeholder About text, deterrent **off**. A missing settings row is recreated
  with these defaults.
- The SPA loads the settings once per visit. If loading fails it falls back to empty About text and
  deterrent off rather than breaking the page.

## About page

`/about` (menubar **About**), public.

1. Everyone sees the rendered body ("Nothing here yet." when empty).
2. Admins get **Edit page**, which swaps the body for a WYSIWYG editor with **Save** / **Cancel**.
   The editor is styled like the rendered page, so what the admin types is what visitors see.
3. **Save** sends the body; the server sanitises it and the page shows the **sanitised** result, so
   anything stripped disappears at once. A success or failure notice appears above the body.
4. **Cancel** discards the draft.

Editor tools: bold, italic, underline, strikethrough, H1–H3, bullet and numbered lists, font family,
font size, text colour, links.

### Sanitising

The About body is the only stored HTML rendered straight into the browser, so it is sanitised **on
save** against an allowlist — a compromised admin session must not become stored XSS against every
visitor.

- Allowed elements: paragraphs, line breaks, rules, bold/italic/underline/strike, sub/superscript,
  headings H1–H4, lists, blockquotes, links, spans, divs. Anything else is removed, keeping its text.
- `<script>` and `<style>` are removed **with their contents** (stops pasted Word styles appearing as
  visible text).
- Inline styles keep only colour, background colour, font size/family/weight/style, text alignment
  and text decoration — nothing that can position content over the app.
- Links may only be `http`, `https` or `mailto`; any other link (e.g. `javascript:`) loses its link
  and keeps its text.
- This is separate from the generated-PDF rich text (cover body etc.), which supports a much
  narrower set (bold, italic, underline, links) — see [pdf-rendering.md](./pdf-rendering.md). The
  About editor is a different, wider editor on purpose: widening the PDF one would let admins author
  formatting the PDF silently drops.

## Image-copy deterrent

Toggle: **Site settings** panel on User Management (`/admin/users`).

When on, every user-facing question image — Browse cards, Generate cards and the question/answer
pages in the detail view — blocks:

- right-click / context menu ("Save image as");
- dragging the image out;
- text/image selection and the iOS long-press "Save Image" sheet.

A transparent layer sits over each image so right-click and long-press hit an empty element; normal
clicks still open the question.

- **Admins are never affected** (they save and inspect images while importing and editing).
- Locked-premium placeholders and admin screens are untouched.
- **It is a deterrent, not protection**: image URLs still reach the browser and can be fetched from
  developer tools. The real access control is the premium paywall, which withholds the URLs
  entirely — see [users-and-premium.md](./users-and-premium.md#how-the-paywall-is-enforced).
