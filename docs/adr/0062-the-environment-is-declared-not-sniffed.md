---
id: 0062
decision: BRAND_OS_ENV names the environment, unset means production, and every env var is read once in app/core/config.py.
applies-to: [app/core/, app/main.py, app/identity/__init__.py, app/identity/routes.py, app/identity/jwt.py, app/core/db.py, app/core/settings.py, app/dashboard/routes.py, app/llm/providers.py, app/storage/__init__.py, .env.example, .github/workflows/ci.yml]
supersedes: none
status: in-force
---

# The environment is declared, not sniffed

2026-09-05, ticket `docs/issues/deploy/02-env-flag-and-settings.md`, route C
(permission / tenant isolation, plus a module boundary). Written before any code.
`docs/contracts/identity.md` reserved this slot in its closing paragraph: "the next route C
question to reach one of them — a second org-selection rule, a change to first-login
provisioning, **an environment-name variable** — writes its own ADR".

## The problem this closes

Two defects with one root, both measured on `saas` @ `bdbb3a8`:

**1. The app infers "am I production" from a hostname.** `_is_local()`
(`app/identity/__init__.py:44-46`) parses `SUPABASE_URL` and answers true for `localhost` and
`127.0.0.1`. Three callers depend on that answer, and all three are permission decisions:

- `app/identity/__init__.py:132` — `IDENTITY_DEV_TOKEN` (a bearer string that authenticates as
  owner of `org_dev`, `app/identity/__init__.py:56-58`) is allowed only when local.
- `app/identity/__init__.py:137` — `IDENTITY_ALLOW_HS256` (accept a JWT signed with the shared
  secret instead of Supabase's JWKS, `app/identity/jwt.py:52-56`) is allowed only when local.
- `app/identity/routes.py:140,148` — when local, a new invite's `accept_url` is returned **in
  the API response body** instead of being emailed.

A self-hosted Supabase on the same box as the API is a supported production topology, and its
`SUPABASE_URL` is `http://127.0.0.1:54321`. That deployment is judged local: two backdoors
open, and every invite token handed back over the API. The hostname was never a statement
about the environment; it was a coincidence that held while the only deployment was a laptop.

**2. Nineteen scattered reads, ten keys, silent defaults.** `os.environ.get` appears 19 times
in `app/` (10 distinct keys). Six of them carry a default that is a working local value —
`DATABASE_URL` falls back to `postgresql://postgres:postgres@127.0.0.1:54322/postgres`
(`app/core/db.py:93-95`), `SUPABASE_URL` to `http://127.0.0.1:54321`
(`app/identity/jwt.py:30`). A deploy that omits or misspells either does not fail; it starts,
and points at a database that is not there, or verifies signatures against a JWKS endpoint that
is not there. The failure surfaces later, as a feature that "does not work".

## The decision

**One variable declares the environment.** `BRAND_OS_ENV` takes `local`, `staging` or
`production`. **Unset means `production`**, and an unrecognised value is a boot failure, not a
fallback. The asymmetry is the whole point: forgetting the variable on a laptop costs one line
in `.env` and a refused start; forgetting it on a server, under any other default, costs a live
service running with development rules. (User's ruling, 2026-09-05.)

`local` is the only value that may enable a development backdoor. `staging` exists in the enum
from day one so that adding a staging environment is a value, not a schema change; today it
behaves exactly like `production`.

**One place reads the environment.** A new `app/core/config.py` holds every environment
variable the app uses, as one typed settings object, built **lazily and cached** — nothing else
calls `os.environ` for configuration. Lazy, not at import: `.env` is loaded by
`app/main.py:86` (`_load_dotenv`, which deliberately does nothing under pytest), and that line
runs before `app.main` imports anything else, so a settings object that is built on first read
is always built after `.env` has been applied. Moving the loader would buy nothing and would
cost the eight assertions in `app/tests/test_main_dotenv.py` for no change in behaviour. ADR 0063
added a second entry point, `app/worker.py`, and it reaches `.env` the same way
`app/meta/daily_pull.py`'s `__main__` block already did — by importing `app.main` — so the
loader still has exactly one home.
`app/main.py` reads the settings once at startup so the check below fires there, not at
whichever request happens to touch configuration first.

**One exception, and it is a tenant-isolation one: `DATABASE_URL` is resolved per call.**
Caching it froze the DSN for the life of the process, and `app/background.app()` compares
`db.dsn()` between calls precisely to notice that it changed — that comparison is how a
background worker stops talking to the previous schema's queue when the connection string moves
(`app/background/__init__.py`'s own header, and `app/tests/test_background.py:31-33`, whose
docstring calls it "the cross-schema/cross-tenant hazard"; `app/tests/conftest.py:161` rewrites
`DATABASE_URL` per test module, which is what exercises it). Found by the first implementation
round on 2026-09-05, which stopped rather than working around it — correctly, because every way
past it is on the forbidden list: a per-call `Settings()` rebuild moves validation off the boot
path, and a global `cache_clear()` from inside `app/background` reaches into every other
caller's configuration.

So `app/core/config.py` exposes `database_url()` beside `settings()`: the live value, with the
local default applied only when the environment is `local`. `settings().database_url` keeps
existing for the boot check, which still requires it outside `local`. This is the one live read
in the codebase, and it is inside the module that is the registry of environment variables —
the ADR's "read once in `app/core/config.py`" holds. Caching a value was never the ruling; the
ruling is one place and one boot failure.

**Boot fails loudly, once, naming everything.** Building the settings object checks the whole
required/forbidden table for the declared environment and raises a single `RuntimeError` listing
**every** violation, not the first — a deploy day where each restart reveals one more missing
key is the failure this ADR exists to prevent.

That single check is why the two startup guards in `app/identity/register()`
(`app/identity/__init__.py:131-141`) move into it. Splitting the table across two files would
restore exactly the behaviour being removed: fix the missing keys, restart, and only then learn
that a dev token is also set. Knowing that `IDENTITY_DEV_TOKEN` is local-only is a property of
the variable, which is what `config.py` is a registry of — it is not identity's authentication
logic leaking into `core`, and `register()` keeps every decision it makes about a request.

`app/core/` gains a file, not a facade: it has no single entry point by design
(`docs/contracts/core.md`), and `config.py` is one more door beside `db.py`. `app/identity/`
is permitted to import it; that is the one line of `docs/contracts/identity.md`'s
"what it must not import" this ADR amends, and it is amended because the alternative — identity
keeping its own hostname sniff — is defect 1.

## What this does not decide

- **Which keys are required where** is the ticket's table, not this ADR's: it is a list that
  grows with every new key, and a list that changes per ticket does not belong in a record that
  claims to be in force.
- **`BRAND_OS_LLM_PROVIDER=codex_cli` in production.** Today it is legal in every environment;
  in a real deployment the local codex CLI does not exist and every AI call would fail. Left
  alone here on purpose — it is a money/provider question, not an environment-naming one, and it
  has its own issue file.
- **Sentry, staging infrastructure, CD, the deployment image's IANA timezone data.** Still
  blocked on choosing a platform (`docs/issues/deploy/issue-07-2-settings-sentry-staging-cd.md`).
- **The frontend's `VITE_*` variables.** They are Vite build-time values baked into the bundle
  (`frontend/src/lib/auth.ts:21-22`); a backend settings object cannot reach them.

## What we looked at

`pydantic-settings` is adopted — the settings library of the framework this project already
runs (FastAPI's own documentation points at it), so pydantic is already resolved as a
dependency and the type layer is the one `pyright` already checks. Nothing else was installed.
The ticket deliberately specifies **behaviour, not that package's API**: the implementer
verifies field, validator and config-dict names against the version `uv` pins, because this
record is not allowed to invent an API from memory.

Rails is the counter-example worth naming: `RAILS_ENV` defaults to `development`, which is the
opposite of the ruling above. That default fits a framework whose common case is a developer
running it locally; ours is a system whose expensive case is a server started by a script that
forgot a line.
