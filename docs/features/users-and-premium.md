# Users & Premium

**Scope:** The three user tiers, admin user management, and the premium paywall wherever it bites —
browse, question detail, and generation. Sign-in itself is in [auth.md](./auth.md).

## Tiers

The stored role values are `admin`, `premium`, and `public` — the last is shown as **"Normal"** in
the UI. A DB check constraint (`ck_user_role`) enforces the set.

| Role | Capabilities |
|---|---|
| **Admin** (1–2 users) | Everything: import, all reference-data CRUD, generation config, user management, full control of cover/header/footer when generating |
| **Premium** | All public capabilities, plus viewing images of premium papers and generating from premium questions |
| **Public / Normal** | View metadata for all questions, images only for non-premium papers; generate from non-premium questions with an admin-configured cover |

Registration always yields `public`. `premium`/`admin` are granted by an admin on the User
Management page — the Subscribe page is a payment stub, not a self-serve upgrade path.
`can_view_premium(user)` (`app/routes/auth.py`) returns true for `admin`/`premium`.

## User management API — admin only

```
GET    /api/users               -- list all users (id, email, first_name, last_name, role, created_at)
PATCH  /api/users/{id}/role     -- change a user's tier. Body: { role: "admin"|"public"|"premium" }.
                                   An admin cannot change their own role (400). Unknown user -> 404.
                                   Invalid role value -> 422.
```

There is no delete-account endpoint.

## Flagging a paper premium

Papers carry an `is_premium` flag. Imported papers are premium **by default** — the admin unticks
the box to make one public.

```
PATCH  /api/papers/{paper_id}/premium  -- set a paper's is_premium flag. Admin only.
                                          Body: { is_premium: bool }. Returns { id, is_premium }.
                                          Unknown paper -> 404. Missing/invalid body -> 422.
```

`app/routes/papers.py::set_paper_premium_route` is a lightweight alternative to the full metadata
`PUT /api/papers/{paper_id}` (which requires every FK id): it loads the paper, sets `is_premium`, and
`db.flush()`es (`get_db` commits on success). It powers the inline Premium checkbox on the admin
Papers list, so an admin can flag/unflag without opening the editor.

## How the paywall is enforced

**The paywall works by withholding the presigned S3 URL**, not by gating a proxy — there is no image
proxy endpoint, so a URL the backend never emits cannot leak.

- **Browse & detail** (`GET /api/questions`, `GET /api/questions/:id`) take *optional* auth
  (`get_current_user_optional`) so they stay public but can tailor the response. For a question
  whose paper has `is_premium = true`, when the viewer is not entitled — anonymous or `public` — the
  backend sets `first_page_url` / page `url` to `null` and `locked: true`. The tile and **all
  metadata are still returned**, so the frontend can show a locked placeholder that prompts a
  subscription.
- **Generation** — `POST /api/generate/select` filters premium papers out of the candidate pool
  entirely for `public` viewers, and `POST /api/generate/paper` returns `403` if any posted
  `question_id` belongs to a premium paper. The UI already prevents adding locked questions; this is
  the server-side guard.

`premium` and `admin` viewers are unrestricted throughout.

## UI

- **User Management** (`/admin/users`, `features/users/UsersList.jsx`): **Name**, Email and Tier
  columns. Name shows `first_name last_name`, or a dash for accounts with neither on file
  (`fullName` in `utils/userName.js`). Tier changes go through a per-row select (Normal / Premium /
  Admin → `api.users.updateRole`); an admin's own row is **disabled** so they can't lock themselves
  out.
- **Subscribe** (`/subscribe`, `pages/SubscribePage.jsx`): a stub — pricing plus a disabled
  Subscribe button. Premium is granted by an admin, not self-serve.
- **Flagging premium papers:** the `is_premium` tickbox appears in three places — the paper editor
  (`PaperMetadataBar`), the import metadata sidebar (`features/import/MetadataSidebar.jsx`), and the
  admin Papers list (`features/papers/PapersList.jsx`) as an inline checkbox in the Premium column.
  On import it is **ticked by default**. The Papers-list checkbox calls
  `api.papers.setPremium(id, is_premium)`, optimistically updates the row, and reverts + shows an
  error on failure (the columns array is built inside the component via `useMemo` so the cell can
  close over the toggle handler).
- **Locked content:** the shared helper `isLocked(item)` (`src/utils/premium.js`) resolves the
  backend signal — `item.locked` if present, else `paper_info.is_premium && !first_page_url` — and
  is reused by `QuestionCard` and the Generate page. `QuestionCard` renders the placeholder asset
  `src/assets/premium-locked.svg` in place of the image; in the Generate cart the Add button becomes
  a **Subscribe** link. Locked cards **stay clickable** — clicking opens `QuestionDetailModal`, which
  shows the same placeholder plus a **Go Premium** button in place of the question/answer images.
- **Generate paywall guards:** **Select All** filters locked questions out before adding to the cart
  (its notice reports how many premium questions were skipped), and `toggleSelect` no-ops on a
  locked item. Before generating, a pre-flight check (`cart.some(isLocked)`) and any `403` from
  `/generate/paper` set a dedicated `genError`, rendered as an amber warning banner right next to
  the Generate button — the Autocreate panel's notice is easy to miss, and a silent failure here is
  worse than a redundant one.
