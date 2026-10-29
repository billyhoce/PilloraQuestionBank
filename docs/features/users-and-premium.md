# Users & Premium

Roles, per-school-level premium access, the paywall, and admin user management. This file holds the
canonical **who can do what** table. Sign-in itself is in [auth.md](./auth.md).

**Code:** `app/services/premium.py`, `app/routes/users.py`, `app/schemas/users.py`,
`app/routes/questions.py`, `app/routes/generate.py`, `app/services/question_serialization.py`,
`frontend/src/features/users/`, `frontend/src/pages/SubscribePage.jsx`,
`frontend/src/utils/premium.js`, `frontend/src/components/NavBar.jsx`
**Related:** [auth.md](./auth.md), [browse.md](./browse.md), [paper-generation.md](./paper-generation.md),
[generation-config.md](./generation-config.md), [site-config.md](./site-config.md),
[reference-data.md](./reference-data.md), [DATA_MODEL.md](../DATA_MODEL.md)

## Roles and premium

- Only two roles: **`admin`** and **`public`** (shown as **"Normal"**).
- **Premium is not a role.** It is the set of **school levels** (Primary, Secondary, …) a user holds.
  A user may hold several. "Is this user premium" is derived from that set, never stored.
- Every school level is automatically a premium plan: adding one adds a plan on `/subscribe` and a
  checkbox in User Management.
- Papers carry an **`is_premium`** flag. Imported papers are premium **by default**; the admin unticks
  it at import, in the paper editor, or inline on the Papers list.
- A premium paper unlocks only for admins and for users holding **its school level** — the school
  level of the paper's **level**. Paper saves refuse a stream and level from different school levels,
  so the two can't disagree.
- Free (non-premium) papers are open to everyone, whatever they hold.

## Who can do what

| Capability | Signed out | Normal | Normal + premium for school level X | Admin |
|---|---|---|---|---|
| Browse, filter, search questions (metadata) | All | All | All | All |
| See question/answer images of free papers | ✓ | ✓ | ✓ | ✓ |
| See images of premium papers | — | — | Papers in X only | All |
| Generate papers (`/generate`) | — (sign in) | Free papers | Free + premium in X | All papers |
| Cover / header / footer when generating | — | Cover always on; title from admin list; body, header, instructions, footer are admin presets | Same as Normal | Full control |
| Read `/about` | ✓ | ✓ | ✓ | ✓ + edit in place |
| View plans (`/subscribe`) | — (sign in) | ✓ | ✓ (owned plans marked) | ✓ (all marked owned) |
| Image-copy deterrent applies (when on) | ✓ | ✓ | ✓ | Never |
| Import papers, manage papers, reference data, generation config, users, site settings | — | — | — | ✓ |

- Registration and Google sign-up always give Normal with no premium.
- Role and premium are set only by an admin on User Management. `/subscribe` is a **payment stub**:
  its Subscribe buttons are disabled and it tells users to ask an admin.
- The first admin is seeded by the initial database migration; further admins are promoted on User
  Management.

## How the paywall is enforced

The paywall **withholds image URLs**; there is no image proxy, so a URL never sent cannot leak.

- **Browse and question detail** stay public. For a question on a premium paper the viewer can't
  open (signed out, Normal, or premium for a *different* school level):
  - All metadata is still returned; image URLs (question and answer pages) are withheld and the item
    is marked locked.
  - The item names the school level needed, since a level name like "1" alone is ambiguous
    (Primary 1 vs Secondary 1).
  - The card shows a locked placeholder and a "🔒 *X* premium" link to `/subscribe?school_level=X`.
    Locked cards stay clickable; the detail view shows the placeholder and a **Get *X* Premium**
    button instead of images.
- **Generation:**
  - Autocreate only draws from papers the user can open; premium papers outside their school levels
    never enter the pool.
  - Rendering a paper is refused if any chosen question is on a paper the user can't open (the
    server-side guard behind the UI).
  - In the Generate UI, locked questions can't be added to the cart; **Select All** skips them and
    says how many premium questions were skipped. A pre-flight check (and any refusal from the
    server) shows a warning next to the Generate button naming the school levels the selection
    needs.
- Admins are unrestricted everywhere.

## Upsell

- **⭐ Go Premium** chip in the menubar shows to any signed-in non-admin whose premium is
  **incomplete** — holding nothing, or fewer school levels than exist. If the school-level count
  can't be loaded, the chip is hidden from partial holders (it is an upsell, so it fails quiet).
- `/subscribe` shows one plan card per school level. A plan the user holds shows "You already have X
  access"; `?school_level=X` highlights the plan a locked question pointed at.

## User management

`/admin/users` (admin only).

Table columns: Name, Email, Sign-in, Joined, Last login, Papers, Tier, Premium Access, Delete.

- **Sign-in** badge: **Invited** (no credentials yet), Password, Google, or Password + Google.
- **Last login**: "Never" until the account first signs in (always so for an unclaimed invite).
- **Papers**: how many PDFs the user has generated.
- **Tier**: Normal / Admin select. An admin cannot change **their own** role.
- **Premium Access**: one checkbox per school level. Each tick saves the whole set (grant and revoke
  in one). Admin rows show "All access". Changes apply optimistically and revert with an error on
  failure.
- **Delete** an account (confirm dialog). Refused for:
  - **yourself** — this is also what guarantees at least one admin always remains;
  - anyone who **imported papers** — the dialog names the count and suggests changing their tier to
    Normal instead.
  Deleting removes the user's premium grants with them.
- **Site settings** panel above the table holds the image-copy deterrent toggle — see
  [site-config.md](./site-config.md#image-copy-deterrent).

## Pre-adding a user

An admin can create an account for someone who hasn't signed up yet (typically they paid first), so
premium is live the moment they do.

- **Add user by email**: email, optional first/last name, school-level checkboxes. Creates a Normal
  account with **no password and no Google link** (shown as **Invited**). Refused if the email
  already has an account.
- Nobody can sign in to an invite. It is **claimed** by either sign-up path on the same address, and
  keeps its role and premium:
  - registering with a password ([auth.md](./auth.md#register-password));
  - signing in with Google ([auth.md](./auth.md#sign-in-with-google)).
- Unclaimed invites stay visible in the list so a mistyped address is noticed.

Edge cases:

| Case | Behaviour |
|---|---|
| Different capitalisation | Same account — emails are normalised. |
| Gmail dot / `+alias` variant | **Never matches** — Google reports the canonical address. The invite form warns the address must be exactly the one they'll sign in with. |
| Person signs in with a different Google address | A separate, unentitled Normal account is created and the invite stays pending. Admin ticks premium on the real row and deletes the stale invite. |
| Someone else registers the invited address first | They inherit the premium. Accepted risk: there is no email verification anywhere, and users are hand-granted at this scale. |
| Password sign-in attempt on an invite | Generic "unknown email or incorrect password" — invites are never disclosed. |
