"""app/identity/routes.py — /api/identity/*. Private: only app/identity/__init__.py imports
this (container contract §1); it is only ever loaded via `register()`, after the package is
fully initialised (see __init__.py's deferred import), so importing `app.identity` names
here at module level is safe.
"""

import os
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel

import app.shared.web as web
from app.core.db import now_utc
from app.identity import ActorContext, Forbidden, NotFound, _is_local, authenticate
from app.identity import repository as repo
from app.shared.web import ApiError

router = APIRouter(prefix="/api/identity")


class UserOut(BaseModel):
    id: UUID
    email: str


class OrgOut(BaseModel):
    id: str
    name: str
    kind: str
    role: str


class MeResponse(BaseModel):
    user: UserOut
    org: OrgOut
    orgs: list[OrgOut]


class RenameOrgRequest(BaseModel):
    name: str


class CreateInviteRequest(BaseModel):
    email: str
    role: Literal["owner", "member"]


class InviteOut(BaseModel):
    id: str
    email: str
    role: str
    expires_at: datetime


class CreateInviteResponse(BaseModel):
    invite: InviteOut
    accept_url: str | None = None


class AcceptInviteResponse(BaseModel):
    org: OrgOut


def _require_owner(actor: ActorContext) -> None:
    if actor.role != "owner":
        raise Forbidden("只有組織的擁有者可以做這件事。")


def _send_invite_email(email: str) -> None:
    """正式環境：透過 Supabase Auth Admin API 寄邀請信；本機開發不寄信，直接把連結
    放進 API 回應（見 create_invite 的 accept_url）。

    ponytail: 只打了 GoTrue admin `/invite` 最小必要參數（email），沒有覆蓋
    redirect_to／使用者 metadata 等進階選項；正式環境真的要接信件遞送時，先照
    Supabase 官方文件核對這支 API 當時的完整參數再擴充，這裡不猜。寄信失敗不擋
    邀請本身建立成功（邀請紀錄已經寫進 DB、token 已經生出來）。
    """
    import httpx

    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not base or not service_key:
        return
    try:
        httpx.post(
            f"{base}/auth/v1/invite",
            json={"email": email},
            headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
            timeout=10.0,
        )
    except httpx.HTTPError:
        pass


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/me", response_model=MeResponse)
def me(request: Request):
    actor = authenticate(request)
    org = repo.get_organisation(web.conn, actor.org_id)
    assert org is not None, f"actor.org_id 指向不存在的組織：{actor.org_id}"
    memberships = repo.list_memberships(web.conn, actor.user_id)
    return MeResponse(
        user=UserOut(id=actor.user_id, email=actor.email),
        org=OrgOut(id=actor.org_id, name=org["name"], kind=org["kind"], role=actor.role),
        orgs=[
            OrgOut(id=m["org_id"], name=m["org_name"], kind=m["org_kind"], role=m["role"])
            for m in memberships
        ],
    )


@router.post("/orgs/current/rename", response_model=OrgOut)
def rename_current_org(request: Request, body: RenameOrgRequest):
    actor = authenticate(request)
    _require_owner(actor)
    name = body.name.strip()
    if not name:
        raise ApiError(400, "invalid_name", "組織名稱不能是空的。")
    repo.rename_organisation(web.conn, actor.org_id, name)
    web.conn.commit()
    return OrgOut(id=actor.org_id, name=name, kind="company", role=actor.role)


@router.post("/invites", response_model=CreateInviteResponse)
def create_invite(request: Request, body: CreateInviteRequest):
    actor = authenticate(request)
    _require_owner(actor)
    email = body.email.strip()
    if not email:
        raise ApiError(400, "invalid_email", "email 不能是空的。")
    invite = repo.create_invite(web.conn, actor.org_id, email, body.role, actor.user_id)
    web.conn.commit()
    local = _is_local()
    if not local:
        _send_invite_email(email)
    return CreateInviteResponse(
        invite=InviteOut(id=invite["id"], email=invite["email"], role=invite["role"],
                          expires_at=invite["expires_at"]),
        # SPA 只掛在 /app（app/main.py、vite.config.ts base），連結一定要帶這個前綴，
        # 不然點下去會打到 FastAPI 的通用 404 頁（票 03-3 §2）。
        accept_url=f"/app/accept-invite?token={invite['token']}" if local else None,
    )


@router.post("/invites/{token}/accept", response_model=AcceptInviteResponse)
def accept_invite(request: Request, token: str):
    actor = authenticate(request)
    invite = repo.get_invite_by_token(web.conn, token)
    if invite is None:
        raise NotFound("找不到這張邀請。")
    if invite["accepted_at"] is not None or invite["expires_at"] < now_utc():
        raise ApiError(410, "invite_gone", "這張邀請已經用過或過期了。")
    repo.accept_invite(web.conn, invite["id"], actor.user_id, invite["org_id"], invite["role"])
    web.conn.commit()
    org = repo.get_organisation(web.conn, invite["org_id"])
    assert org is not None, f"invite.org_id 指向不存在的組織：{invite['org_id']}"
    return AcceptInviteResponse(
        org=OrgOut(id=org["id"], name=org["name"], kind=org["kind"], role=invite["role"])
    )


@router.delete("/members/{user_id}")
def remove_member(request: Request, user_id: UUID):
    actor = authenticate(request)
    _require_owner(actor)
    target = repo.get_membership(web.conn, actor.org_id, user_id)
    if target is None:
        raise NotFound("這個人不是這個組織的成員。")
    if target["role"] == "owner" and repo.count_owners(web.conn, actor.org_id) <= 1:
        raise ApiError(409, "last_owner", "不能移除最後一個擁有者——組織至少要留一個擁有者。")
    repo.remove_membership(web.conn, actor.org_id, user_id)
    web.conn.commit()
    return {"ok": True}
