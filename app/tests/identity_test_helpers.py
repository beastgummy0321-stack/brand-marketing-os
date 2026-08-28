"""app/tests/identity_test_helpers.py — shared helpers for the identity test suite
(ticket 03-1). Not a test module itself (no `Test*`/`test_*` collected names beyond the
helper functions below, and pytest only collects files matching `test_*.py`).
"""

import os
import time
from uuid import uuid4

import jwt
from fastapi.routing import APIRoute


def flatten_routes(app) -> list:
    """FastAPI 0.141 起 `include_router()` 是惰性的（`_IncludedRouter`／
    `_EffectiveRouteContext` 包一層，不是立刻攤平成 `APIRoute`），`app.routes` 直接看
    只看得到最外層。這裡遞迴展開，回傳每一條真正的路由（`.path`／`.methods`／
    `.endpoint` 三個屬性可用，不保證是 `APIRoute` 實例本身）。"""
    out = []
    for r in app.routes:
        out.extend(_flatten_one(r))
    return out


def _flatten_one(r) -> list:
    if isinstance(r, APIRoute):
        return [r]
    type_name = type(r).__name__
    if type_name == "_IncludedRouter":
        out = []
        for candidate in r.effective_candidates():
            out.extend(_flatten_one(candidate))
        return out
    if type_name == "_EffectiveRouteContext":
        return [r]
    return []


def mint_hs256(
    sub: str | None = None,
    email: str = "test@example.com",
    *,
    exp_delta: int = 3600,
    secret: str | None = None,
    aud: str | None = "authenticated",
    alg: str = "HS256",
) -> str:
    """比照 Supabase 簽出來的 access token 該有的必要 claims（sub/aud/exp/email），走
    HS256 + 本機 `SUPABASE_JWT_SECRET`（`IDENTITY_ALLOW_HS256=1` 才會被
    app.identity.jwt.decode() 接受，conftest.py 已預設打開）。"""
    secret = secret or os.environ["SUPABASE_JWT_SECRET"]
    sub = sub or str(uuid4())
    now = int(time.time())
    payload = {"sub": sub, "email": email, "iat": now, "exp": now + exp_delta}
    if aud is not None:
        payload["aud"] = aud
    return jwt.encode(payload, secret, algorithm=alg)
