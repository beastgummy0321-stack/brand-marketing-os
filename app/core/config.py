"""app/core/config.py — one more door beside `db.py` (`app/core/` has no facade by design,
`docs/contracts/core.md` "Entry path"), not a facade over them (ADR 0062).

Holds every environment variable the backend reads, as one settings object built lazily and
cached — nothing else reads the process environment directly for configuration, except this
file's own `database_url()` (§5a below; after this ticket, the only other direct read of it left
in `app/` is `app/main.py`'s `_load_dotenv()`). Lazy, not at import: `.env` is loaded by
`app/main.py`'s `_load_dotenv()`, which runs before `app.main` imports anything else, so a
settings object built on first *call* to `settings()` is always built after `.env` has been
applied.

`BRAND_OS_ENV` names the environment (`local` / `staging` / `production`); unset means
`production`, any other value is a boot failure, never a fallback (user's ruling, 2026-09-05).
`local` is the only value that may enable a development backdoor. Building the settings object
checks the whole required/forbidden table for the declared environment and raises a single
`RuntimeError` listing every violation, not the first — a deploy day where each restart reveals
one more missing key is the failure this exists to prevent.

One exception, and it is a tenant-isolation one (ADR 0062, ticket §5a): `DATABASE_URL` is not
frozen in the `settings()` cache. `app/background.app()` compares `db.dsn()` between calls to
notice the connection string changed and rebuilds rather than keep talking to the previous
schema's queue — a cached DSN breaks that (`app/tests/test_background.py`'s
`test_dsn_resolves_late_not_at_import`). `database_url()` below is the live read: `dsn()` in
`app/core/db.py` calls it, never `settings().database_url`.
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_VALID_ENVS = ("local", "staging", "production")

# 本機開發預設值（原本住在 app/core/db.py:93-95、app/identity/jwt.py:30）：只在
# BRAND_OS_ENV=local 且對應變數沒設時填入，staging／production 一律要求明講，不退回這裡。
_LOCAL_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
_LOCAL_SUPABASE_URL = "http://127.0.0.1:54321"

# 表格是資料，不是十一個各自的 if——新增一個受管變數只改這兩個 tuple。
_REQUIRED_OUTSIDE_LOCAL = (
    ("database_url", "DATABASE_URL", "production 必須明確給，不會退回本機預設值"),
    ("supabase_url", "SUPABASE_URL", "production 必須明確給，不會退回本機預設值"),
    ("supabase_service_role_key", "SUPABASE_SERVICE_ROLE_KEY", "production 必須明確給"),
)
_LOCAL_ONLY = "這是開發後門，只能在 BRAND_OS_ENV=local 使用"
_FORBIDDEN_OUTSIDE_LOCAL = (
    ("identity_dev_token", "IDENTITY_DEV_TOKEN", _LOCAL_ONLY),
    ("identity_allow_hs256", "IDENTITY_ALLOW_HS256", _LOCAL_ONLY),
    ("brand_os_today", "BRAND_OS_TODAY", "這是測試用的『今天』凍結旗標，只能在 local 使用"),
)
# 上面那張表是「有值就違規」；這張是「只有某一個值違規，其他值合法」。
_FORBIDDEN_VALUES_OUTSIDE_LOCAL = (
    ("brand_os_llm_provider", "BRAND_OS_LLM_PROVIDER", "codex_cli",
     "codex_cli 是本機那支 CLI（ADR 0032），雲端主機上沒有這支程式，"
     "設下去每一次 AI 呼叫都會安靜失敗"),
    ("brand_os_llm_provider", "BRAND_OS_LLM_PROVIDER", "scripted",
     "scripted 是 e2e 後端專用的罐頭回覆（F06-I05），不是真的模型，"
     "設下去每一次 AI 呼叫都回固定的假資料"),
    ("brand_os_job_queue", "BRAND_OS_JOB_QUEUE", "memory",
     "memory 是 e2e 後端專用（F06-I05），背景工作會被直接丟掉、永遠不會執行"),
)


class Settings(BaseSettings):
    """一個變數一個屬性，名字是變數名的小寫。`env_ignore_empty`：`FOO=`（設成空字串）跟
    沒設一樣，不會被 pydantic 的 bool 解析炸掉，也不會被當成「明確給了空字串」這種
    半吊子狀態——跟這張票「required＝有值且非空、forbidden＝沒設或空」的定義對齊。
    """

    model_config = SettingsConfigDict(env_ignore_empty=True)

    brand_os_env: str = "production"

    database_url: str = ""
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""

    identity_dev_token: str = ""
    identity_allow_hs256: bool = False
    brand_os_today: str = ""

    anthropic_api_key: str = ""
    brand_os_llm_model: str = ""
    brand_os_llm_provider: str = ""
    brand_os_job_queue: str = ""

    @property
    def is_local(self) -> bool:
        return self.brand_os_env == "local"

    @model_validator(mode="after")
    def _check_environment_table(self) -> Settings:
        if self.brand_os_env not in _VALID_ENVS:
            raise RuntimeError(
                f"BRAND_OS_ENV={self.brand_os_env!r} 不合法，只能是 "
                f"{'／'.join(_VALID_ENVS)} 其中之一（沒有設定＝production）。\n"
                "本機開發請在 .env 加一行 BRAND_OS_ENV=local。"
            )

        if self.is_local:
            # 只有本機才填本機預設值；staging／production 就算這裡沒填，上面的
            # required 檢查已經先擋下了，不會有機會用到這個分支的預設值。
            if not self.database_url:
                self.database_url = _LOCAL_DATABASE_URL
            if not self.supabase_url:
                self.supabase_url = _LOCAL_SUPABASE_URL
            return self

        violations = []
        for attr, var_name, reason in _REQUIRED_OUTSIDE_LOCAL:
            if not getattr(self, attr):
                violations.append(f"  - {var_name} 沒有設定：{reason}")
        for attr, var_name, reason in _FORBIDDEN_OUTSIDE_LOCAL:
            if getattr(self, attr):
                violations.append(f"  - {var_name} 有值：{reason}")
        for attr, var_name, bad_value, reason in _FORBIDDEN_VALUES_OUTSIDE_LOCAL:
            if getattr(self, attr) == bad_value:
                violations.append(f"  - {var_name}={bad_value}：{reason}")

        if violations:
            raise RuntimeError(
                f"BRAND_OS_ENV={self.brand_os_env}（沒有設定＝production），"
                "這些環境變數不對：\n"
                + "\n".join(violations)
                + "\n本機開發請在 .env 加一行 BRAND_OS_ENV=local。"
            )
        return self


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings()


def database_url() -> str:
    """The live `DATABASE_URL` — NOT cached, unlike every other variable in this file (ADR 0062
    §5a). `app/core/db.py:dsn()` calls this, never `settings().database_url`: `settings()` is a
    process-lifetime singleton, and `app/background.app()` relies on `dsn()` changing value the
    moment `DATABASE_URL` does, to notice it must rebuild rather than keep talking to the
    previous schema's queue. The local default applies only when the environment is `local`
    (read from the cached `settings()` — `BRAND_OS_ENV` itself does not change mid-process); the
    required-outside-local check already happened in `settings()`'s validator, so a healthy
    process never reaches the forbidden-empty case here."""
    value = os.environ.get("DATABASE_URL", "")
    if not value and settings().is_local:
        value = _LOCAL_DATABASE_URL
    return value
