# Users & Premium

**Scope:** The user roles, per-school-level premium access, admin user management, and the paywall
wherever it bites — browse, question detail, and generation. Sign-in itself is in [auth.md](./auth.md).

## Roles and premium access

There are only **two** stored role values: `admin` and `public` (shown as **"Normal"** in the UI). A
DB check constraint (`ck_user_role`) enforces the set.

**Premium is not a role.** It is the **set of school levels** a user has paid for, held in
`user_premium_school_level`. Premium is sold per school level — Primary and Secondary are separate
products — and a user may hold several, so a single role value could never express it. Nothing
stores "is this user premium": it is derived from the entitlement rows, so a user's apparent tier
can never disagree with what they can actually open.

| Who | Capabilities |
|---|---|
| **Admin** (1–2 users) | Everything: import, all reference-data CRUD, generation config, user management, full control of cover/header/footer when generating. Unrestricted by the paywall — entitlement rows are irrelevant to an admin |
| **Normal with premium for a school level** | All Normal capabilities, plus viewing images of, and generating from, premium papers **in that school level** |
| **Normal** (`public`, no entitlements) | View metadata for all questions, images only for non-premium papers; generate from non-premium questions with an admin-configured cover |

Registration always yields `public` with no entitlements. Both the role and the entitlements are set
by an admin on the User Management page — the Subscribe page is a payment stub, not a self-serve
upgrade path.

## Which premium group a paper belongs to

A premium paper's group is the school level of its **`level`** (`paper.level.school_level_id`). A
paper also reaches a school level through its `stream`, but only the level is authoritative for the
paywall — and paper writes **reject the two disagreeing** with a `422`
(`school_level_conflict` in `app/services/paper_admin.py`, called from the import confirm and the
paper `PUT`). Without that guard a paper could read as Secondary everywhere in the UI while being
sold to Primary customers. See [ingestion.md](./ingestion.md).

## The gate — `app/services/premium.py`

One module owns the policy, in two shapes that must agree:

```python
entitled_school_level_ids(user) -> set[int] | None   # None = unrestricted (admin); set() = anonymous
premium_gate(user) -> Callable[[Paper], bool]        # resolve entitlements once, apply per row
can_view_paper(user, paper) -> bool                  # the single-paper convenience form
restrict_premium_pool(query, user)                   # the SQL form, for the generation pool
```

`premium_gate` is what serializers take, so a page of results doesn't re-read the viewer's
entitlements per row. `restrict_premium_pool` is the same rule expressed in SQL — change one, change
the other. `tests/test_premium_gate.py` asserts the two agree.

## User management API — admin only

```
GET    /api/users                            -- list all users. Each row carries id, email,
                                                first_name, last_name, role, created_at,
                                                premium_school_levels: [{id, name}], plus
                                                last_login_at, papers_generated and the derived
                                                has_password / has_google / is_invited flags.
                                                The hash and google_sub themselves are excluded.

POST   /api/users                            -- pre-create an account for an address that has not
                                                signed up yet. Body: { email, first_name?,
                                                last_name?, role?, school_level_ids? }. Creates a
                                                credential-less row plus its entitlements, so
                                                premium is live the moment they register.
                                                Duplicate email -> 409; unknown school level -> 422.
                                                201 + the list-row shape.

DELETE /api/users/{id}                       -- delete an account; entitlements cascade. 204.
                                                Deleting yourself -> 400. A user who imported
                                                papers -> 409 naming the count (Paper.created_by is
                                                ON DELETE RESTRICT). Unknown -> 404.

PATCH  /api/users/{id}/role                  -- change a user's role. Body: { role: "admin"|"public" }.
                                                An admin cannot change their own role (400).
                                                Unknown user -> 404. Invalid role (including the
                                                retired "premium") -> 422.

PUT    /api/users/{id}/premium-school-levels -- replace the set of school levels a user has premium
                                                access to. Body: { school_level_ids: [int] }.
                                                A full replace, so one payload both grants and
                                                revokes. Unknown user -> 404; unknown school level
                                                id -> 422. No self-change guard: an admin already
                                                sees every school level, so self-granting changes
                                                nothing and can't lock anyone out.
```

`/api/auth/me` also returns `premium_school_levels`, so the SPA knows which plans the user owns.

Deleting a school level cascades its entitlement rows away (`ON DELETE CASCADE`). In practice the
`level`/`stream` foreign keys already `RESTRICT` the delete, so it rarely bites — see
[reference-data.md](./reference-data.md).

**No separate "last admin" guard on delete.** Refusing self-delete already makes one unnecessary: the
caller is an admin and cannot be the target, so deleting an admin always leaves at least the caller
behind. A `remaining == 0` check could never fire, so it isn't there.

## Pre-adding a user (invites)

An admin can create an account for someone who has not signed up yet — typically because they paid
first — so their premium access is live the moment they do. It is **not** a separate table: the
invite is an ordinary `app_user` row with **no password and no `google_sub`**, which
`User.is_invited` derives (see [DATA_MODEL.md](../DATA_MODEL.md#google-linked-accounts) for the four
credential states). Entitlements attach through the normal FK, and invites are listed like any other
row so a mistyped address is visible rather than silently doing nothing.

**Claiming.** Both sign-up paths land on the same row and keep its role and premium:

- **Password** — `POST /api/auth/register` looks the address up first and, if the row is an unclaimed
  invite, sets its `password_hash` instead of returning 409. Without this an invited user could not
  create an account *at all*. A row that already has a credential still returns 409, so registering
  can never take over someone else's account.
- **Google** — needs no new code. `_resolve_google_user` already falls through `google_sub` → email →
  create, and the email branch is exactly what attaches a `google_sub` to the pre-made row.

### What can go wrong with Google, and what we do about it

| | Behaviour |
|---|---|
| **Case** | Fixed. Google's `email` claim is canonical lower-case; addresses are normalized on every write and lookup, so `Billy@Gmail.com` and `billy@gmail.com` are one account. Before this, an invite in the wrong case produced a second, unentitled row. |
| **Gmail dot / `+` aliases** | **Not** handled, on purpose. `bill.y@`, `billy+qb@` and `@googlemail.com` reach the same inbox, but Google reports the canonical address, so an aliased invite never matches. Normalizing them would be wrong for every non-Gmail provider. Mitigated in the UI: the invite form says the address must be the exact one they sign in with. |
| **A different Google address** (work Workspace vs personal Gmail) | Creates a fresh unentitled row and leaves the invite pending. The admin ticks premium on the real row and deletes the stale invite — which is why unclaimed invites stay visible. |
| **Google changes the account's email** | Matching is `google_sub`-first, so a linked account survives it; `app_user.email` then goes stale. Pre-existing behaviour, unchanged. |
| **No email verification on registration** | **Accepted risk.** Anyone who knows an invited address can register it first and inherit the premium. Already true of open registration generally — there is no email verification anywhere — but an invite makes the prize bigger than an empty account. Acceptable at 1–10 hand-granted users. |
| **User enumeration** | None added. The "created with Google" 409 branch requires a `google_sub`, which an invite lacks, so a password attempt against one falls through to the generic 401. |

## Flagging a paper premium

Papers carry an `is_premium` flag; the school level decides *who* it unlocks for. Imported papers are
premium **by default** — the admin unticks the box to make one public.

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
  (`get_current_user_optional`) so they stay public but can tailor the response. For a question whose
  paper is premium in a school level the viewer doesn't hold — anonymous, `public`, or premium for a
  *different* school level — the backend sets `first_page_url` / page `url` to `null` and
  `locked: true`. The tile and **all metadata are still returned**, so the frontend can show a locked
  placeholder that prompts a subscription. `paper_info.school_level_name` names the group the viewer
  needs; `level_name` alone can't, because "1" is both Primary 1 and Secondary 1.
- **Generation** — `POST /api/generate/select` runs the candidate pool through
  `restrict_premium_pool`, so premium papers outside the viewer's school levels never enter it (free
  papers always do, whatever the viewer holds). `POST /api/generate/paper` returns `403` if any
  posted `question_id` belongs to a paper the viewer can't open. The UI already prevents adding
  locked questions; this is the server-side guard.

Admins are unrestricted throughout.

## UI

- **User Management** (`/admin/users`, `features/users/UsersList.jsx`): **Name**, Email, **Sign-in**,
  **Joined**, **Last login**, **Papers**, Tier, **Premium Access** and a delete action. Widened to
  `max-w-[90%]` — nine columns don't fit the old `max-w-4xl`. Name shows `first_name last_name`, or a
  dash for accounts with neither on file (`fullName` in `utils/userName.js`). Sign-in is a badge
  reading **Invited** / Password / Google / Password + Google, derived from the `has_password` /
  `has_google` / `is_invited` flags. Last login shows "Never" until the account has signed in, which
  is always the case for an unclaimed invite. The Tier select offers only Normal / Admin
  (`api.users.updateRole`); an admin's own row is **disabled** so they can't lock themselves out.
  Premium Access renders one checkbox per school level (from `api.schoolLevels.list()`); ticking one
  sends the whole resulting set through `api.users.setPremiumSchoolLevels`, optimistically updating
  the row and reverting + showing an error on failure — the same pattern as the inline Premium
  checkbox on the Papers list. Admin rows show "All access" instead of checkboxes.
- **Add user by email** (`features/users/InviteUserModal.jsx`): email + names + the same school-level
  checkboxes, posting `api.users.create` and appending the row. The email field warns that it must be
  the exact address they will sign in with, since a Gmail dot or `+alias` variant will never match
  their Google account.
- **Delete** per row (hidden on the admin's own row), through the shared
  `components/ConfirmDialog.jsx`. A backend refusal — most often "imported N paper(s)" — is shown in
  the dialog and the row stays.
- **Site settings** panel above the table: the site-wide **Discourage copying of question images**
  toggle, sent as a *partial* `api.siteConfig.update({ protect_images })` so it cannot overwrite the
  About page content edited elsewhere. See [site-config.md](./site-config.md).
- **Subscribe** (`/subscribe`, `pages/SubscribePage.jsx`): one plan card per school level, built from
  `api.schoolLevels.list()`. A plan the user already holds shows an owned banner instead of the
  (disabled) Subscribe button; admins see every plan as owned. `?school_level=<name>` highlights one
  card, which is how a locked question points at the plan it needs. Still a payment stub — premium is
  granted by an admin.
- **Locked content:** the shared helpers in `src/utils/premium.js` resolve the backend signal —
  `isLocked(item)` (`item.locked` if present, else `paper_info.is_premium && !first_page_url`),
  `requiredSchoolLevel(item)` (the group the viewer is missing), `subscribeHref(item)` (the deep
  link), and `hasSchoolLevel(user, name)`. `QuestionCard` renders `src/assets/premium-locked.svg` in
  place of the image and its CTA reads "🔒 Secondary premium"; in the Generate cart the Add button
  becomes that same link. Locked cards **stay clickable** — clicking opens `QuestionDetailModal`,
  which shows the placeholder plus a **Get Secondary Premium** button in place of the images.
- **Generate paywall guards:** **Select All** filters locked questions out before adding to the cart
  (its notice reports how many premium questions were skipped), and `toggleSelect` no-ops on a locked
  item. Before generating, a pre-flight check and any `403` from `/generate/paper` set a dedicated
  `genError`, rendered as an amber warning banner right next to the Generate button — the Autocreate
  panel's notice is easy to miss, and a silent failure here is worse than a redundant one. The
  pre-flight message names the school levels the selection needs, since "subscribe to unlock" is
  useless when there is more than one plan.
- **Nav upsell:** the "⭐ Go Premium" chip (`components/NavBar.jsx`) shows to any non-admin whose
  premium access is **incomplete** — including a partially-subscribed user, who can then buy the
  school level they're missing. Telling "holds some" from "holds everything" needs the total number
  of school levels, so the NavBar fetches `GET /api/school-levels` (only for users the chip could
  apply to). A user holding **nothing** is shown the chip immediately, without waiting on that fetch,
  since no count can make zero entitlements complete. If the fetch fails the chip is simply withheld
  from partial subscribers — it's an upsell, not a feature, so it fails quiet.
