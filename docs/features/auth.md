# Auth

**Scope:** Registration, password login, Google OAuth 2.0, session handling, and the security
posture around them — backend and UI. Roles and per-school-level premium access are in
[users-and-premium.md](./users-and-premium.md); the `User` table is in
[DATA_MODEL.md](../DATA_MODEL.md); Google Cloud Console setup is in
[DEPLOYMENT.md](../DEPLOYMENT.md#google-oauth-setup).

Accounts are created either manually (email + password) or with Google. Either way the session is a
JWT in an httpOnly cookie.

## Endpoints

```
POST   /api/auth/register       -- public registration (always role "public").
                                   Body: { first_name, last_name, email, password }.
                                   Names are trimmed; blank or >100 chars -> 422.
POST   /api/auth/login          -- sets JWT in httpOnly cookie. Unknown email and wrong
                                   password are one generic 401. An account created with
                                   Google (no password on file) instead gets 409 with a
                                   "use Sign in with Google" message.
POST   /api/auth/logout         -- clears cookie
GET    /api/auth/me             -- current authenticated user, including first_name/last_name
                                   and the has_password / has_google flags describing how it
                                   signs in
GET    /api/auth/providers      -- { "google": bool } — whether Google sign-in is configured
                                   on this deployment. Public.
```

### Google OAuth 2.0

```
GET    /api/auth/google/login    -- 307 to Google's consent screen. Plants a random
                                    `state` nonce in a 10-minute httpOnly cookie.
                                    503 if the GOOGLE_* env vars are unset.
GET    /api/auth/google/callback -- Google redirects the browser here with ?code&state.
                                    On success: sets the same JWT cookie as /login and
                                    307s to "/". On failure: 307 to /login?error=<code>,
                                    where <code> is one of google_cancelled,
                                    google_state_mismatch, google_email_unverified,
                                    google_failed.
```

Both are browser navigations, not XHR — the frontend links to `/api/auth/google/login` directly.
Failures redirect rather than returning JSON because the user is mid-redirect in a browser, where a
JSON body would be a dead end.

## Security

- **Passwords:** bcrypt via `bcrypt.gensalt()` (default cost factor 12).
- **Auth tokens:** JWT (`python-jose`, HS256) in an `httpOnly`, `secure`, `samesite=lax` cookie
  named `access_token`, 7-day expiry. `JWT_SECRET_KEY` comes from env and falls back to an insecure
  default — it **must** be set in production.
- **Admin routes:** the `require_admin` dependency (`app/routes/auth.py`) checks
  `user.role == "admin"` and returns `403` otherwise. Applied to all reference-data writes, all
  `/api/import/*`, and the `/api/users` routes.
- **Optional auth:** `get_current_user_optional` is the non-raising variant used by the public
  browse endpoints so they can tailor responses to the viewer's tier.
- **Input validation:** every API input is a Pydantic model (`app/schemas/`), including
  password-strength validation on registration.
- **CORS:** **not implemented** — no `CORSMiddleware` in `app/main.py`, and none is needed. Nginx
  serves the SPA and the API at the same origin, and Google redirects the browser to a same-origin
  backend route rather than making a cross-origin request.
- **Rate limiting:** **not implemented** — there is no limiter on `/api/auth/*` or anywhere else.

### Google OAuth internals

Server-side **authorization-code** flow: `app/services/google_oauth.py` (pure helpers) plus the two
`/api/auth/google/*` routes. The browser only ever sees a redirect URL — the client ID, the client
secret and every Google token stay on the server, and no Google JavaScript is loaded. Configured by
`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI`; when any is unset
`is_configured()` is false, `/api/auth/providers` reports `{"google": false}` and the UI hides the
button. Scopes are `openid email profile` only — all non-sensitive, so the consent screen needs no
Google verification review.

- **CSRF:** `/google/login` mints a `secrets.token_urlsafe(32)` nonce, stores it in a 10-minute
  `httpOnly` `oauth_state` cookie, and passes it as `state`. The callback compares the two with
  `secrets.compare_digest` and aborts on any mismatch, so a callback the browser never initiated
  cannot log anyone in.
- **Profile trust:** the callback reads the profile from Google's OIDC **userinfo endpoint** using
  the freshly exchanged access token, rather than verifying the `id_token` JWT locally. The response
  arrives over TLS straight from Google in a server-to-server call the client cannot influence, so
  it is equally trustworthy without a JWKS fetch and cache.
- **Account linking:** matching is by `google_sub` first, then by email — but **only when Google
  reports `email_verified`**. An unverified address is rejected outright
  (`google_email_unverified`), since it is not proof of identity and would otherwise be a route to
  hijacking an existing account. A verified match attaches `google_sub` to the existing row and
  preserves its `role` **and its premium school levels**. [DATA_MODEL.md](../DATA_MODEL.md) tabulates the three password/Google
  combinations a `User` row can be in.
- **Passwordless accounts:** `password_hash` is `NULL` for Google-created accounts.
  `verify_password` returns `False` for a NULL/empty hash rather than letting bcrypt raise. Password
  login against such an account short-circuits to a **`409`** telling the user to use "Sign in with
  Google" — a password attempt there can never succeed, so the generic 401 would just look like a
  forgotten password and loop them. This is a **deliberate user-enumeration trade-off**: it confirms
  the address has a Google account. It is the only such disclosure — it fires only when the account
  has *no* password at all, so an account with both a password and a Google link (and every unknown
  email) still returns the single generic `401`.

## UI

`/login`, `/register`; **Log out** lives in the menubar's account dropdown (`<UserMenu />`, see
[ARCHITECTURE.md](../ARCHITECTURE.md#navigation-app-shell)). After login — and for
already-authenticated visits to `/login`/`/register` — **all roles redirect to `/`**. Non-admins are
redirected away from `/admin/*`. The session lives in the httpOnly cookie; **no token handling in
JS**.

### Two ways in

Both pages offer a manual form and a Google button; the user picks either.

- **Register** (`pages/RegisterPage.jsx`) collects **First name, Last name**, Email, Password and
  Confirm password. Passwords are matched client-side; the strength rules are enforced server-side
  and only described in hint text. On success it redirects to `/login` — it does not
  auto-authenticate.
- **Sign in with Google** (`components/GoogleSignInButton.jsx`) is a plain
  `<a href="/api/auth/google/login">`, **not** a react-router `<Link>` — the flow needs a real
  browser navigation so the backend can set the `oauth_state` cookie and redirect on to Google. No
  Google JavaScript, no client ID in the bundle, and consequently **no `VITE_*` env vars anywhere in
  this app**. Availability comes from `GET /api/auth/providers` at page load; when it reports
  `google: false` (or the call fails) the button and its "or" divider are hidden.
- The Google callback finishes with a **full page load** of `/`, so `AuthContext`'s existing
  `api.auth.me()` on mount picks up the session — no extra client wiring.
- A failed Google sign-in lands on `/login?error=<code>`. `LoginPage` maps the four backend codes to
  copy shown in the shared `<ErrorBanner />`; an unrecognised code is ignored rather than echoed.
- **Password on a Google-created account** shows *"This account was created with Google. Use \"Sign
  in with Google\" instead."* in the same banner, with the button right below it. The backend sends
  this as a `409`, and `friendlyMessage` in `api/client.js` passes a 409 `detail` through verbatim —
  the generic *"Unknown email or incorrect password"* rewrite applies only to a `401` on
  `/api/auth/login`.

### Displaying the user

`utils/userName.js` owns the fallback, since accounts predating the name fields (and Google accounts
that report no given/family name) store empty strings:

- `fullName(user)` → `"First Last"`, or `''`. Used in the admin Users table, where the email is
  already in its own column.
- `displayName(user)` → the same, falling back to the **email address**. Used by `<UserMenu />` for
  the account button.
