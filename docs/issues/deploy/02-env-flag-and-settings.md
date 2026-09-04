# 02 — the environment is declared, and every env var is read in one place

Route C (permission / tenant isolation, plus one module boundary). Authority: **ADR 0062**
(`docs/adr/0062-the-environment-is-declared-not-sniffed.md`) — read it first; it holds the
reasoning and this ticket does not repeat it. Contract pages that govern this work:
`docs/contracts/identity.md`, `docs/contracts/core.md`, `rules/container-contract.md`.

Precedence reminder: constitution > ADR > contract page > this ticket. Two contract pages were
amended **before** this ticket was written (identity's "what it must not import" now allows
`app.core.config`; its startup-gate paragraph says the gate moves). If anything below still
contradicts a page above it, that is `blocked-upstream`, not something to correct quietly.

## What

### 1. New module file: `app/core/config.py`

`app/core/` has no facade by design (`docs/contracts/core.md`, "Entry path") — this is one more
door beside `db.py`, not a facade over them. It holds every environment variable the backend
reads, as one settings object built lazily and cached, using **pydantic-settings**
(`uv add pydantic-settings`; `uv.lock` must be in the diff and `uv sync --frozen` must pass).

**Verify that package's API against the version `uv` pins — do not take field, validator or
config-class names from this ticket or from memory.** This ticket specifies behaviour only.

Exported shape (names below are the contract; everything else in the file is private):

```python
# app/core/config.py
from app.core.config import settings

settings()                    # cached; the FIRST call validates and may raise RuntimeError
settings().brand_os_env       # "local" | "staging" | "production"
settings().is_local           # brand_os_env == "local"

# one attribute per variable, named after it in lower case, all `str` except where noted:
#   brand_os_env, database_url, supabase_url, supabase_service_role_key, supabase_jwt_secret,
#   identity_dev_token, identity_allow_hs256 (bool), brand_os_today,
#   anthropic_api_key, brand_os_llm_model, brand_os_llm_provider
```

- Unset optional variables are `""` (not `None`), so the existing `or` chains at the call sites
  stay one-liners.
- `identity_allow_hs256` is a `bool`: today the code compares the raw string to `"1"`
  (`app/identity/__init__.py:137`, `app/identity/jwt.py:52`). Whatever truthy spellings
  pydantic accepts for a bool are accepted; `.env.example` keeps using `1`.
- After validation, `database_url` and `supabase_url` are **always non-empty**: in `local` the
  settings object fills in today's local defaults, which move here from `app/core/db.py:93-95`
  and `app/identity/jwt.py:30`; in `staging`/`production` they are required, so an empty one is
  a boot failure and never a silent localhost fallback.

### 2. `BRAND_OS_ENV`, and the table the boot check enforces

`local` | `staging` | `production`. **Unset means `production`** (user's ruling, 2026-09-05).
Any other value is a boot failure, never a fallback. `staging` behaves exactly like
`production` today; it exists in the enum so that adding a staging environment later is a value,
not a schema change.

| variable | `local` | `staging` / `production` |
|---|---|---|
| `DATABASE_URL` | optional — local default | **required** |
| `SUPABASE_URL` | optional — local default | **required** |
| `SUPABASE_SERVICE_ROLE_KEY` | optional | **required** |
| `IDENTITY_DEV_TOKEN` | optional | **forbidden** |
| `IDENTITY_ALLOW_HS256` | optional | **forbidden** |
| `BRAND_OS_TODAY` | optional | **forbidden** |
| `SUPABASE_JWT_SECRET` | optional | optional |
| `ANTHROPIC_API_KEY` | optional | optional |
| `BRAND_OS_LLM_MODEL` | optional | optional |
| `BRAND_OS_LLM_PROVIDER` | optional | optional |

"required" = present and non-empty. "forbidden" = unset or empty. Why each one is where it is:

- `SUPABASE_SERVICE_ROLE_KEY` is required outside local because without it `app/storage` raises
  only when someone uploads (`app/storage/__init__.py:58-61`) and invite mail silently does not
  send (`app/identity/routes.py:83-85` returns early).
- `BRAND_OS_TODAY` is a test seam that freezes "today" (`app/dashboard/routes.py:22-24`).
  Left set on a server it shows every org numbers for the wrong day.
- `SUPABASE_JWT_SECRET` has no rule: it is only ever consulted when `IDENTITY_ALLOW_HS256` is
  on (`app/identity/jwt.py:52-56`), which is already forbidden outside local.
- `ANTHROPIC_API_KEY` is optional everywhere: it has a Vault/DB fallback
  (`app/core/settings.py:180`). `BRAND_OS_LLM_PROVIDER` is **deliberately unruled** here — see
  "Out of scope".

### 3. One boot failure, naming everything

The first `settings()` call checks the whole table and raises **one** `RuntimeError` listing
**every** violation — not the first one. Shape (wording may differ, the three properties may
not: every violation present, each naming its variable, and a last line telling a developer
what to do):

```
BRAND_OS_ENV=production（沒有設定＝production），這些環境變數不對：
  - DATABASE_URL 沒有設定：production 必須明確給，不會退回本機預設值
  - SUPABASE_URL 沒有設定：production 必須明確給，不會退回本機預設值
  - IDENTITY_DEV_TOKEN 有值：這是開發後門，只能在 BRAND_OS_ENV=local 使用
本機開發請在 .env 加一行 BRAND_OS_ENV=local。
```

`app/main.py` reads `settings()` once at startup, immediately after the existing
`_load_dotenv()` call (`app/main.py:86`), so the failure lands at boot rather than at whichever
request first touches configuration. `_load_dotenv` and `_parse_env_file` **stay in
`app/main.py`, unchanged** (ADR 0062 says why; `app/tests/test_main_dotenv.py` must not need
editing — if it does, something moved that should not have).

### 4. `_is_local()` is deleted; the two identity guards move

- `app/identity/__init__.py:44-46` (`_is_local`) is deleted. Its three callers read
  `settings().is_local` instead: `app/identity/__init__.py:132`, `:137`,
  `app/identity/routes.py:140` (which decides whether a new invite's `accept_url` comes back in
  the API response — ADR 0062, and it keeps exactly that behaviour, now keyed off the flag).
  `app/identity/routes.py:17` imports `_is_local` from the package; that import goes.
- The two `RuntimeError` guards in `register()` (`app/identity/__init__.py:131-141`) move into
  the boot check of §3 — ADR 0062 rules this, including why it is not a boundary violation.
  `register()` keeps only the mount. Their user-visible effect is unchanged: a backdoor set
  outside `local` refuses to start.

### 5. All 19 reads go through the settings object

Every `os.environ` read in `app/` becomes an attribute read. Measured, `saas` @ `bdbb3a8`:
19 sites, 10 keys — `app/core/db.py:93`, `app/core/settings.py:180,209,268`,
`app/dashboard/routes.py:24`, `app/identity/__init__.py:45,98,131,137`,
`app/identity/jwt.py:30,52,56`, `app/identity/routes.py:83,84`, `app/llm/providers.py:43`,
`app/storage/__init__.py:51,58`, and `app/main.py:80-81` (that pair is `_load_dotenv`'s own
writer — it stays). The constants `API_KEY_ENV_VAR`, `LLM_MODEL_ENV_VAR`
(`app/core/settings.py:25,27`), `_CODEX_CLI_ENV_VAR`, `_CODEX_CLI_ENV_VALUE`
(`app/llm/providers.py:37-38`) lose their reason to exist once the names live in `config.py`;
delete the ones that end up with no caller, and leave any that still have one.

After this ticket, `os.environ` appears in `app/` only inside `app/main.py`'s dotenv loader.

### 6. Templates, CI, tests

- `.env.example` gains `BRAND_OS_ENV`, **commented out**, with a note: uncomment for local
  development, a real deployment sets it in its own environment. It must **not** ship an active
  `BRAND_OS_ENV=local` line — that file already ships `IDENTITY_DEV_TOKEN=test-dev-token`
  uncommented, and a template that declares itself local would hand a verbatim cloud copy both
  backdoors. This is the same hole `Hs256StartupGuardTest` exists to watch
  (`app/tests/test_architecture_boundaries.py:1114-1120`).
- `.github/workflows/ci.yml` must export `BRAND_OS_ENV=local` before the **e2e smoke** step
  (that step boots a real backend on :8720 with no `.env` file — `frontend/playwright.config.ts`
  `webServer`). Without it CI goes red on this ticket's own change, and red for the right
  reason: the CI backend really would be declaring itself production.
- `app/tests/conftest.py:35-37` adds `BRAND_OS_ENV=local` alongside the existing
  `setdefault`s, for the same reason.
- `Hs256StartupGuardTest` and the `IDENTITY_DEV_TOKEN` guard test in
  `app/tests/test_identity_auth.py` are re-pointed at the moved gate: they set
  `BRAND_OS_ENV=production` instead of a non-local `SUPABASE_URL`, and assert against
  `app.core.config`, not `register()`. **Re-pointing a moved guard only** — the assertion that a
  backdoor outside local refuses to start must survive, and the `.env.example` half of
  `Hs256StartupGuardTest` must survive unchanged plus gain the `BRAND_OS_ENV` line above.
- Exactly **one** new test: the boot check reports **all** violations at once, not the first
  (that is the one property of §3 that nothing existing covers, and the one a later "simplify"
  would quietly break). No test per variable — the table is data, not eleven behaviours.

### Out of scope (do not implement; a `reject` follows if these appear)

- `BRAND_OS_LLM_PROVIDER=codex_cli` outside local. Real trap, wrong ticket, own issue file.
- Sentry, staging infrastructure, CD, the image's IANA timezone data — still blocked on
  choosing a platform (`docs/issues/deploy/issue-07-2-settings-sentry-staging-cd.md`).
- The frontend's `VITE_*` variables: build-time, baked into the bundle, out of reach.
- Any change to what `authenticate()`, `_resolve_org()` or `jwt.decode()` decide about a
  request. This ticket moves where a value is read, never what is done with it.

## How we know it's done

Every number below is produced by a command, never typed.

1. **Machine gate, in this order.** All green, no exceptions granted:
   - `uv sync --frozen`
   - `uv run ruff check app`
   - `uv run pyright`
   - `uv run pytest app/tests/test_architecture_boundaries.py app/tests/test_identity_auth.py app/tests/test_identity_orgs.py app/tests/test_main_dotenv.py app/tests/test_core_db_pool.py app/tests/test_background.py app/tests/test_dashboard_overview.py app/tests/test_settings_api.py app/tests/test_storage.py -q`
     (drop from that list only a file that does not exist; say which and why)
   - `cd frontend && npx tsc -b --noEmit && npm run build`
   - `cd frontend && npm run e2e` — the one end-to-end smoke, required on this ticket, with
     `supabase start` already up. It is the only check that proves the server still boots.
2. **`os.environ` is gone from `app/` except the dotenv loader.**
   `git ls-files 'app/*.py' | grep -v '^app/tests/' | xargs grep -n "os\.environ\|os\.getenv"`
   returns only `app/main.py:80-81` (line numbers may shift). Paste the output.
3. **`_is_local` has no callers left.** `git ls-files | xargs grep -n "_is_local"` returns no
   hit under `app/` — docs and this ticket may still name it. Paste the output.
4. **The boot check is proven red once, both directions** (global rule: a new check counts only
   after it has been seen to fail). Run each, paste the real output, restore:
   - `BRAND_OS_ENV=production DATABASE_URL= SUPABASE_URL= IDENTITY_DEV_TOKEN=x uv run python -c "import app.main"`
     → `RuntimeError` naming **`DATABASE_URL`, `SUPABASE_URL` and `IDENTITY_DEV_TOKEN` in one
     message**. Three names in one raise is the check; two would be a fail.
   - The same command with `BRAND_OS_ENV=local` → starts.
   - `BRAND_OS_ENV=nonsense uv run python -c "import app.main"` → fails, does not fall back.
5. **Two frozen numbers may be moved, and only these two.** Both are `frozen baseline`s under
   the global "never widen a tolerance list" rule; `docs/tech-debt.md` §六 is the 2026-09-02
   user ruling that governs the exception, and its test is quoted there: *"新增的行數是那張票的
   交付物本身，還是為了繞過閘門塞進來的？"* This ticket's answer is "the deliverable" for both.
   - `KNOWN_MODULE_SIZES` (`app/tests/test_architecture_boundaries.py:1331`): `app/core` grows
     by `config.py`; `app` and `app/identity` should **shrink**. Set every row that moved to the
     **measured** number with **no slack** (slack disables the ratchet), one line of reason each,
     in the style of the rows already there. Today's values: `app` 553, `app/core` 1630,
     `app/identity` 539, `app/dashboard` 645.
   - `TEST_LINES_CEILING` (`:1286`, today `18919`): only if the one new test of §6 plus the
     re-pointing actually pushes it over. Measured number, no slack, reason above the line.
   - Any **other** gate that goes red is `blocked-upstream`, not a dial to turn. This ticket
     authorises these two rows and nothing else — the `schedule-extract-state` precedent
     (`app/tests/test_architecture_boundaries.py:1120-1128`) is the standard here.
6. **The three documents that describe the moved gate are true again**:
   - `docs/contracts/identity.md` — the startup-gate paragraph and "Exported shapes" now say
     `register()` only mounts, with the current line numbers.
   - `docs/contracts/core.md` — `config.py` gets a row in the entry-path table and its exported
     shape listed, in that page's existing format.
   - `.env.example` — §6 above.
7. **`git diff --name-only` matches `## Shared files touched`.** A file in the diff that the
   field below does not name means the ticket was written against a wrong picture of the code:
   report it, do not widen the field.
8. **Report the volume**: lines of code and of tests added, the new totals for `app/core` and
   `app/identity`, and any file above 640 lines (80% of the 800 cap).

## Shared files touched

Pasted from the station-① scan, `saas` @ `bdbb3a8`. Every name that stops existing or changes
meaning in this slice, searched across the whole repo (`git ls-files` plus `docs/issues/*/*.md`),
unscoped by directory and by file type. Identifiers show `file:line`; the ten variable names
show the files, because their hit lists are long and mostly comments and tests.

```
### _is_local
app/identity/__init__.py:44:def _is_local() -> bool:
app/identity/__init__.py:132:    if dev_token and not _is_local():
app/identity/__init__.py:137:    if os.environ.get("IDENTITY_ALLOW_HS256") == "1" and not _is_local():
app/identity/routes.py:17:from app.identity import ActorContext, Forbidden, NotFound, _is_local, authenticate
app/identity/routes.py:140:    local = _is_local()
app/tests/test_architecture_boundaries.py:1390:    "app/identity": 539,  # 票 identity-hs256-startup-guard：`_is_local()` 從 routes.py 搬進
docs/contracts/identity.md:40:`_is_local()` with that reading; until it lands, the code still sniffs the hostname and this
docs/issues/deploy/issue-is-local-env-flag.md:1:# `_is_local()` 只認 localhost／127.0.0.1

### API_KEY_ENV_VAR
app/core/settings.py:25:API_KEY_ENV_VAR = "ANTHROPIC_API_KEY"
app/core/settings.py:180:    api_key = os.environ.get(API_KEY_ENV_VAR) or _read_vault_api_key(conn, org_id=org_id)
app/core/settings.py:209:    return "env" if os.environ.get(API_KEY_ENV_VAR) else "db"

### LLM_MODEL_ENV_VAR
app/core/settings.py:27:LLM_MODEL_ENV_VAR = "BRAND_OS_LLM_MODEL"
app/core/settings.py:268:        or os.environ.get(LLM_MODEL_ENV_VAR)

### _CODEX_CLI_ENV_VAR
app/llm/providers.py:37:_CODEX_CLI_ENV_VAR = "BRAND_OS_LLM_PROVIDER"
app/llm/providers.py:43:    return os.environ.get(_CODEX_CLI_ENV_VAR) == _CODEX_CLI_ENV_VALUE

### _CODEX_CLI_ENV_VALUE
app/llm/providers.py:38:_CODEX_CLI_ENV_VALUE = "codex_cli"
app/llm/providers.py:43:    return os.environ.get(_CODEX_CLI_ENV_VAR) == _CODEX_CLI_ENV_VALUE

### _load_dotenv  (stays in app/main.py — listed because the scan must show it was checked)
app/main.py:61:def _load_dotenv() -> int:
app/main.py:86:_load_dotenv()
app/meta/daily_pull.py:255:    # 變數的地方（app/main.py `_load_dotenv()`）——兩條路徑都需要，所以留在最前面。
app/tests/test_main_dotenv.py:46:    def test_load_dotenv_is_a_noop_under_pytest(self):
app/tests/test_main_dotenv.py:47:        self.assertEqual(main._load_dotenv(), 0)
app/tools/boot_launcher.py:12:.env 金鑰不必在這裡讀——app.main 自己會讀（`_load_dotenv`，2026-08-23 那次「換個啟動

### _parse_env_file  (stays in app/main.py)
app/main.py:43:def _parse_env_file(text: str) -> dict:
app/main.py:79:    for key, value in _parse_env_file(env_path.read_text(encoding="utf-8-sig")).items():
app/tests/test_main_dotenv.py:16,20,24,27,30,33,40  (eight assertions on the parser)

### _today_override
app/dashboard/routes.py:22:def _today_override():
app/dashboard/routes.py:32:            main_mod.conn, org_id=actor.org_id, today=_today_override()),
app/dashboard/routes.py:44:            main_mod.conn, org_id=actor.org_id, brand_id=brand_id, today=_today_override()),

### BRAND_OS_ENV  (the new name — nothing in app/ or frontend/ collides)
docs/contracts/identity.md:38
docs/contracts/identity.md:73

### SUPABASE_URL (files)
.env.example .github/workflows/ci.yml app/identity/__init__.py app/identity/jwt.py app/identity/routes.py app/storage/__init__.py app/tests/conftest.py app/tests/test_identity_auth.py app/tests/test_identity_orgs.py docs/contracts/identity.md frontend/.env.example frontend/src/lib/auth.ts

### SUPABASE_SERVICE_ROLE_KEY (files)
.env.example .github/workflows/ci.yml app/identity/routes.py app/storage/__init__.py app/tests/conftest.py docs/adr/0043-one-bucket-and-the-org-id-is-the-first-folder.md

### SUPABASE_JWT_SECRET (files)
.env.example app/identity/jwt.py app/tests/conftest.py app/tests/identity_test_helpers.py CLAUDE.md

### IDENTITY_DEV_TOKEN (files)
.env.example app/identity/__init__.py app/main.py app/tests/conftest.py app/tests/test_architecture_boundaries.py app/tests/test_identity_auth.py docs/contracts/identity.md supabase/seed.sql

### IDENTITY_ALLOW_HS256 (files)
.env.example app/identity/__init__.py app/identity/jwt.py app/tests/conftest.py app/tests/identity_test_helpers.py app/tests/test_architecture_boundaries.py app/tests/test_identity_auth.py CLAUDE.md docs/contracts/identity.md

### DATABASE_URL (files)
.env.example app/background/__init__.py app/core/db.py app/tests/conftest.py app/tests/test_background.py app/tests/test_core_db_pool.py docs/contracts/core.md

### BRAND_OS_TODAY (files)
app/dashboard/routes.py app/tests/test_dashboard_brand_month.py app/tests/test_dashboard_guide_card_links.py app/tests/test_dashboard_guide_cards_wiring.py app/tests/test_dashboard_overview.py

### ANTHROPIC_API_KEY (files)
app/core/settings.py app/tests/test_architecture_boundaries.py app/tests/test_intake.py app/tests/test_intake_api.py app/tests/test_intake_api_paste.py app/tests/test_intake_research_reports_api.py app/tests/test_library_api.py app/tests/test_product_handoff.py app/tests/test_product_scan.py app/tests/test_products_api.py app/tests/test_settings_api.py docs/adr/0031-agent-runs-are-isolated-from-the-developer-s-own-config.md frontend/src/components/settings/ApiKeySection.tsx

### BRAND_OS_LLM_MODEL (files)
app/core/settings.py app/tests/test_intake.py app/tests/test_product_handoff.py app/tests/test_product_scan.py app/tests/test_settings_api.py

### BRAND_OS_LLM_PROVIDER (files)
app/llm/providers.py app/main.py CLAUDE.md docs/adr/0032-the-agent-cli-is-a-provider-and-it-returns-text.md
```

Notes a reader of that list needs:

- `CLAUDE.md`, `supabase/seed.sql`, `docs/adr/0031`, `docs/adr/0032`, `docs/adr/0043` and
  `frontend/**` hits are **prose or the frontend's own `VITE_*` pair** — nothing there changes.
  `CLAUDE.md`'s line about self-signing an HS256 JWT is still true after this ticket.
- Test files in those lists that only *read* a variable through the app need no edit; the ones
  this ticket does edit are named in "What" §6 and nowhere else.

## Contradiction check

**The pair that can contradict**: done-check 4's third case (`BRAND_OS_ENV=nonsense` must fail
to boot) against done-check 1's e2e smoke plus §6's CI change. Input that shows it: any process
that boots the app without `BRAND_OS_ENV` set and without a `.env` — exactly the CI e2e job
today. Under this ticket's own default that process declares itself production, and the e2e
backend then dies on the required `DATABASE_URL`/`SUPABASE_URL` while the ticket also demands
that e2e be green. They agree **only** if §6's CI export is done; skip it and the two checks are
directly opposed. That is why the CI line is in "What", not a footnote — and it is the first
thing to look at if e2e goes red.

Second, weaker pair: done-check 2 ("`os.environ` gone from `app/` except the loader") against
"What" §3 ("`_load_dotenv` and `_parse_env_file` stay in `app/main.py`"). An implementer who
reads check 2 as an absolute would move the loader into `config.py` to satisfy it, breaking the
eight assertions in `app/tests/test_main_dotenv.py` and the ADR's stated reason. Check 2 names
the exception; if it still reads as ambiguous, that is `blocked-upstream`, not a coin flip.

**Not a contradiction, stated so it is not mistaken for one**: `.env.example` must *not* declare
`BRAND_OS_ENV=local` (§6) while the developer's own `.env` *must* (§3's error message). The
template is copied to servers; the untracked local file is not.
