# Contract — identity (who is logged in, and which org they are acting for)

Five things and nothing else (container contract §8). Reasoning lives in the ADRs named below;
it is not repeated here, because a second copy goes stale.

Written 2026-09-03, ahead of the `identity-hs256-startup-guard` slice, because a route C ticket
touching a module registers that module first. It records what `app/identity/` **is**, not what
it should be.

## Entry path

`app/identity/__init__.py` — a real single entry file, unlike `core`. `jwt.py`, `repository.py`
and `routes.py` are private; nothing outside the package imports them, and `routes.py` is reached
only through `register()`.

## Exported shapes

```
ActorContext(user_id: UUID, org_id: str, role: str, email: str)          # frozen dataclass
                                          # email is `""` when the JWT carries no email claim
                                          # (`app/identity/__init__.py:113`), never None
authenticate(request) -> ActorContext
register(app: FastAPI) -> None            # mounts /api/identity/*; raises at startup, see below
Unauthenticated, Forbidden                # re-exported app.shared.web.ApiError subclasses
```

Callers, both of them:

- `app/shared/web.py:258` (`require_actor`) — **lazy import**, because `app.identity` imports
  `app.shared.web` at module level. Moving that import to the top of the file re-forms the cycle.
- `app/main.py:438` (`register`).

`register()` is also a **startup gate**, not only a mount: it raises `RuntimeError` when a
development backdoor is enabled outside the local environment — `IDENTITY_DEV_TOKEN`
(`app/identity/__init__.py:131-136`) and `IDENTITY_ALLOW_HS256` (`:137-141`). A misconfigured
deploy is meant to die at boot, loudly, rather than serve.

**Both of those move out of this module** (ADR 0062): the environment is named by `BRAND_OS_ENV`
rather than sniffed from the `SUPABASE_URL` hostname, and every environment rule is checked once
in `app/core/config.py` so one boot failure names every violation instead of the first.
`register()` then only mounts. Ticket `docs/issues/deploy/02-env-flag-and-settings.md` is the
slice that does it; until it lands, the two paragraphs above describe the code and this one
describes where it is going — the one place in this file that is ahead of `app/`.

## Error shapes

Everything leaves as an `app.shared.web.ApiError` subclass — `Unauthenticated` (401),
`Forbidden` (403), `NotFound` (404) — rendered by `app/main.py:487`'s envelope as
`{"error": {"code", "message"}}`. Two named codes other modules and the frontend depend on:
`forbidden_org` (the `X-Org-Id` header names an org this user has no membership in, or the user
has zero memberships) and the 401 family from `jwt.decode`, which turns every `PyJWTError`
subclass into one `Unauthenticated`.

**Known inconsistency, not a decision**: the rest of the app answers 404 through `require_brand`
with a bare `{"detail": …}`. Two envelopes, three frontend readers of `.detail`. Board item 07-3
owns unifying them; it is an API-contract change, so it does not happen inside another ticket.

## What it must not import

- Nothing from `app.brand_intelligence`, `app.schedule`, `app.meta`, `app.orders`, `app.intake`,
  `app.brand_web`, `app.llm` — identity sits under all of them and knows about none.
- Only `app.core.db` (`Conn`, `ConnProxy`, `new_id`, `now_utc`), `app.core.config` (the settings
  object, ADR 0062) and `app.shared.web`.
- `app.shared.web` must not import `app.identity` at module level (see the cycle note above).

Identity's own queries are the one place tenant scoping is **absent on purpose** — it is the code
that decides which org you are, so it cannot filter by one. `app/core/db.py:238` names this
exemption; `UnscopedTenantReadScanTest` in `app/tests/test_architecture_boundaries.py` freezes it.
An unscoped read anywhere else is a defect.

## Decisions in force

- ADR 0061 — an org invite is accepted only by a signed-in user whose email equals the invited
  email, compared case-insensitively; `gone` is answered before identity.
- ADR 0062 — `BRAND_OS_ENV` names the environment and unset means production; only `local` may
  enable `IDENTITY_DEV_TOKEN`, `IDENTITY_ALLOW_HS256`, or hand an invite's `accept_url` back in
  the API response. This module no longer decides that question from a hostname.

The rest of the module still holds authentication and org resolution with no decision record
behind them. The next route C question to reach one of them — a second org-selection rule, a
change to first-login provisioning — writes its own ADR rather than leaning on these.
