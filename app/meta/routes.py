"""app/meta/routes.py — /api/meta/*. Private: only app/meta/__init__.py imports this
(container contract §1); it is only ever loaded via `register()`.
"""

from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel

import app.shared.web as web
from app.core.audit import write_audit
from app.meta import graph
from app.meta import repository as repo

router = APIRouter(prefix="/api/meta")


class TokenRequest(BaseModel):
    token: str


class AccountOut(BaseModel):
    id: str
    account_id: str
    name: str
    currency: str
    connected_at: datetime
    bound_brand_ids: list[str]


class AccountsResponse(BaseModel):
    token_tail: str | None
    accounts: list[AccountOut]


def _accounts_response(org_id: str) -> AccountsResponse:
    credential = repo.get_credential(web.conn, org_id)
    bound = repo.bound_brand_ids_by_account(web.conn, org_id)
    accounts = [
        AccountOut(
            id=row["id"],
            account_id=row["account_id"],
            name=row["name"],
            currency=row["currency"],
            connected_at=row["connected_at"],
            bound_brand_ids=bound.get(row["id"], []),
        )
        for row in repo.list_accounts(web.conn, org_id)
    ]
    return AccountsResponse(
        token_tail=credential["token_tail"] if credential else None, accounts=accounts
    )


@router.post("/token", response_model=AccountsResponse)
async def connect_token(request: Request, body: TokenRequest):
    actor = web.require_actor(request)
    token = body.token.strip()
    if not token:
        raise web.ApiError(400, "invalid_token", "請貼上 Meta 權杖。")
    # 先打 Graph API 確認這個權杖真的能用——列不出帳號的權杖什麼都不存（設計檔）。
    try:
        accounts = graph.list_ad_accounts(token)
    except graph.GraphError as exc:
        raise web.ApiError(
            400, "meta_token_rejected", f"Meta 拒絕了這個權杖：{exc.message}"
        ) from exc
    repo.save_token(web.conn, actor.org_id, token)
    repo.upsert_accounts(web.conn, actor.org_id, accounts)
    web.conn.commit()
    return _accounts_response(actor.org_id)


@router.get("/accounts", response_model=AccountsResponse)
async def list_accounts(request: Request):
    actor = web.require_actor(request)
    return _accounts_response(actor.org_id)


@router.post("/brands/{brand_id}/accounts/{ad_account_id}")
async def bind_account(request: Request, brand_id: str, ad_account_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    account = repo.get_account(web.conn, actor.org_id, ad_account_id)
    if account is None:
        raise web.NotFound("找不到這個廣告帳戶。")
    inserted = repo.bind(web.conn, actor.org_id, brand_id, ad_account_id)
    if inserted:
        write_audit(
            web.conn, org_id=actor.org_id, brand_id=brand_id, entity_type="meta_ad_account",
            entity_id=ad_account_id, action="bind", actor=str(actor.user_id),
        )
    web.conn.commit()
    return {"ok": True}


@router.delete("/brands/{brand_id}/accounts/{ad_account_id}")
async def unbind_account(request: Request, brand_id: str, ad_account_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    deleted = repo.unbind(web.conn, actor.org_id, brand_id, ad_account_id)
    if not deleted:
        raise web.NotFound("這個品牌沒有綁定這個廣告帳戶。")
    write_audit(
        web.conn, org_id=actor.org_id, brand_id=brand_id, entity_type="meta_ad_account",
        entity_id=ad_account_id, action="unbind", actor=str(actor.user_id),
    )
    web.conn.commit()
    return {"ok": True}
