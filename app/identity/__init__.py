"""app/identity/__init__.py — single entry point (container contract §1, ticket 03-1).

Shapes other modules may use:
    ActorContext(user_id, org_id, role, email)
    authenticate(request) -> ActorContext          # raises Unauthenticated (401) / Forbidden (403)
    register(app)                                    # mounts /api/identity/*
    Unauthenticated, Forbidden                       # ApiError subclasses (app.shared.web.ApiError)

Internals (`jwt.py`, `repository.py`, `routes.py`) are private — nothing outside this
package imports them directly. Callers: `app/shared/web.py` (`require_actor`, lazy-imported
to avoid a module-load cycle — see that function's docstring) and `app/main.py` (`register`).

First-login: an unknown `sub` gets an `app_user` row, a personal organisation
(kind='personal', name=email), and an owner membership, all in one transaction (ticket 03-1
§"On first authenticated request for an unknown sub").

Org resolution: `X-Org-Id` header must name an org the user has a membership in, else 403
`forbidden_org`; without the header, the user's personal org (else 403 `forbidden_org` — a
user always has exactly one personal org after first login, so this only fires for the dev
token's fixed actor if seed data is missing).

Dev bypass: `IDENTITY_DEV_TOKEN` — when the bearer token equals it, the actor is the seed dev
user (`00000000-0000-0000-0000-000000000001`) in `org_dev` as owner, no JWT involved.
`register()` refuses to start (`RuntimeError`) if this env var is set while `SUPABASE_URL`
is not a localhost/127.0.0.1 URL.
"""

import os
from dataclasses import dataclass
from urllib.parse import urlparse
from uuid import UUID

from fastapi import FastAPI, Request

import app.shared.web as web
from app.identity import jwt as identity_jwt
from app.identity import repository as repo
from app.shared.web import ApiError, Forbidden, NotFound, Unauthenticated  # noqa: F401 — re-export

_DEV_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
_SEED_ORG_ID = "org_dev"


@dataclass(frozen=True)
class ActorContext:
    user_id: UUID
    org_id: str
    role: str
    email: str


def _dev_actor() -> ActorContext:
    return ActorContext(user_id=_DEV_USER_ID, org_id=_SEED_ORG_ID, role="owner", email="dev@local")


def _resolve_org(request: Request, user_id: UUID) -> tuple[str, str]:
    org_id = request.headers.get("X-Org-Id")
    if org_id:
        membership = repo.get_membership(web.conn, org_id, user_id)
        if membership is None:
            raise Forbidden("你不在這個組織裡，或這個組織不存在。", code="forbidden_org")
        return org_id, membership["role"]
    membership = repo.get_personal_membership(web.conn, user_id)
    if membership is None:
        raise Forbidden("找不到可用的組織。", code="forbidden_org")
    return membership["org_id"], membership["role"]


def _first_login(user_id: UUID, email: str) -> None:
    repo.create_user(web.conn, user_id, email)
    org_id = repo.create_personal_organisation(web.conn, email)
    repo.create_membership(web.conn, org_id, user_id, "owner")
    web.conn.commit()


def authenticate(request: Request) -> ActorContext:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise Unauthenticated()
    token = auth_header[len("Bearer "):].strip()
    if not token:
        raise Unauthenticated()

    dev_token = os.environ.get("IDENTITY_DEV_TOKEN")
    if dev_token and token == dev_token:
        return _dev_actor()

    try:
        claims = identity_jwt.decode(token)
    except Exception:  # jwt.PyJWTError family (bad sig／expired／unsupported alg) 與 JWKS
        # 抓取失敗（PyJWKClientError／連線錯誤）一律視同「這個令牌不能用」→ 401，
        # 不是伺服器錯誤——呼叫端（前端）看到 401 就會導去登入頁重新拿令牌。
        raise Unauthenticated() from None

    try:
        user_id = UUID(str(claims.get("sub")))
    except (ValueError, TypeError):
        raise Unauthenticated() from None
    email = claims.get("email") or ""

    if repo.get_user(web.conn, user_id) is None:
        _first_login(user_id, email)

    org_id, role = _resolve_org(request, user_id)
    return ActorContext(user_id=user_id, org_id=org_id, role=role, email=email)


def register(app: FastAPI) -> None:
    """掛 /api/identity/* 路由。啟動檢查：`IDENTITY_DEV_TOKEN` 只能在本機（`SUPABASE_URL`
    是 localhost/127.0.0.1）設定，避免正式環境不小心留著開發後門。"""
    dev_token = os.environ.get("IDENTITY_DEV_TOKEN")
    if dev_token:
        host = urlparse(os.environ.get("SUPABASE_URL", "")).hostname or ""
        if host not in ("localhost", "127.0.0.1"):
            raise RuntimeError(
                "IDENTITY_DEV_TOKEN 只能在本機開發環境使用"
                "（SUPABASE_URL 必須是 localhost 或 127.0.0.1，目前不是）"
            )
    from app.identity import routes as identity_routes  # 延遲 import：見檔頭「Internals」

    app.include_router(identity_routes.router)
