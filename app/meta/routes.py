"""app/meta/routes.py — /api/meta/*. Private: only app/meta/__init__.py imports this
(container contract §1); it is only ever loaded via `register()`.
"""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Request
from pydantic import BaseModel

import app.shared.web as web
from app.background import enqueue as background_enqueue
from app.background import is_active as background_is_active
from app.background import outcome as background_outcome
from app.core import settings as coresettings
from app.core.audit import write_audit
from app.meta import daily_pull, graph
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


# F31-I03 (Contract N): Graph's own text never reaches the user. A valid token without
# `ads_read` gets "(#100) Unsupported get request" on `me/adaccounts`, which reads like a wrong
# URL; 10/200-299 are Graph's permission codes.
_MISSING_SCOPE_MESSAGE = (
    "這把權杖看不到廣告帳戶，通常是產生權杖時沒有勾 ads_read 權限。"
    "請重新產生一把有勾 ads_read 的權杖再貼上。"
)


_NO_ACCOUNTS_MESSAGE = (
    "這把權杖讀不到任何廣告帳戶：可能填錯，或這個帳號沒有廣告帳戶的權限。"
)


def _token_rejection(exc: graph.GraphError) -> web.ApiError:
    """F47 Contract G: only `auth` says Meta rejected the token; a Meta outage or an unknown
    error says Meta could not be read and nothing was stored."""
    kind = graph.classify_error(exc)
    shown = f"（代碼 {exc.code}）" if exc.code is not None else ""
    if kind == graph.ERROR_SCOPE:
        return web.ApiError(400, "meta_token_missing_scope", _MISSING_SCOPE_MESSAGE)
    if kind == graph.ERROR_AUTH:
        return web.ApiError(
            400, "meta_token_rejected",
            f"Meta 拒絕了這個權杖{shown}。請確認權杖沒有過期、是從正確的帳號產生的。",
        )
    return web.ApiError(
        502, "meta_unreachable", f"Meta 暫時讀不到{shown}，這把權杖還沒驗證、沒有存。請稍後再試。"
    )


@router.post("/token", response_model=AccountsResponse)
def connect_token(request: Request, body: TokenRequest):
    actor = web.require_actor(request)
    token = body.token.strip()
    if not token:
        raise web.ApiError(400, "invalid_token", "請貼上 Meta 權杖。")
    # 先打 Graph API 確認這個權杖真的能用——列不出帳號的權杖什麼都不存（設計檔）。
    try:
        accounts = graph.list_ad_accounts(token)
    except graph.GraphError as exc:
        raise _token_rejection(exc) from exc
    if not accounts:  # F47 Contract G: a token that lists no account is not stored
        raise web.ApiError(400, "meta_token_no_accounts", _NO_ACCOUNTS_MESSAGE)
    repo.save_token(web.conn, actor.org_id, token)
    repo.upsert_accounts(web.conn, actor.org_id, accounts)
    web.conn.commit()
    return _accounts_response(actor.org_id)


@router.get("/accounts", response_model=AccountsResponse)
def list_accounts(request: Request):
    actor = web.require_actor(request)
    return _accounts_response(actor.org_id)


@router.post("/brands/{brand_id}/accounts/{ad_account_id}")
def bind_account(request: Request, brand_id: str, ad_account_id: str):
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
def unbind_account(request: Request, brand_id: str, ad_account_id: str):
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


# ---- 票 05：品牌頁的本月花費／成效 ---------------------------------------------------

class CampaignSpendOut(BaseModel):
    campaign_id: str
    campaign_name: str
    spend: float
    impressions: int
    clicks: int
    roas: float | None  # None＝未追蹤，前端據此顯示「未追蹤」，不是 0


class SpendSummaryResponse(BaseModel):
    last_pull_at: datetime | None  # None＝這個品牌綁定的帳號一次都還沒成功拉過
    # F31-I03 (Contract N): newest pulled_at of the rows summed below (None only with no rows),
    # and the Chinese label of their attribution window (repo.attribution_label).
    data_pulled_at: datetime | None
    attribution_label: str | None
    campaigns: list[CampaignSpendOut]
    total: CampaignSpendOut


@router.get("/brands/{brand_id}/spend", response_model=SpendSummaryResponse)
def brand_spend(request: Request, brand_id: str):
    """本月（今天所在的日曆月，[月初, 下月初) 半開區間）逐活動花費／成效＋一列總計，
    見 repo.spend_summary 的總 ROAS 算法（花費加權，任一列未追蹤整組回 None）。**只看
    campaign 層**（票 S1：這支端點的畫面契約沒變，仍然是逐活動；adset／ad 層的數字給
    排程模組的樹狀節點用，不在這裡）。

    「今天」用組織自己的時區算（票 04-1b）：用 UTC 的話，台北時間每個月 1 號早上 8 點
    以前打開這一頁，看到的會是上個月的花費。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    account_ids = repo.bound_account_ids_for_brand(web.conn, actor.org_id, brand_id)
    today = coresettings.today_for_org(web.conn, org_id=actor.org_id)
    month_start = today.replace(day=1)
    month_end = (month_start + timedelta(days=32)).replace(day=1)
    summary = repo.spend_summary(
        web.conn, actor.org_id, account_ids, month_start, month_end, level="campaign",
    )
    # repo.spend_summary 票 S1 起回 entity_id／entity_name（三層共用一支函式）——這支端點
    # 的 HTTP 回應形狀不變（票 S1 D2）：對回 campaign_id／campaign_name，
    # frontend/src/lib/metaApi.ts、CockpitPage.tsx 一個字都不用改。多出來的 ctr／cpc／
    # cpm／cpa 四個鍵，CampaignSpendOut 沒有對應欄位，Pydantic v2 預設 extra="ignore"
    # 會安靜丟掉，不會 500。
    campaigns = [
        CampaignSpendOut(
            campaign_id=e["entity_id"], campaign_name=e["entity_name"], spend=e["spend"],
            impressions=e["impressions"], clicks=e["clicks"], roas=e["roas"],
        )
        for e in summary["entities"]
    ]
    total = CampaignSpendOut(
        campaign_id="total", campaign_name="總計", spend=summary["total"]["spend"],
        impressions=summary["total"]["impressions"], clicks=summary["total"]["clicks"],
        roas=summary["total"]["roas"],
    )
    freshness = repo.spend_freshness(
        web.conn, actor.org_id, account_ids, month_start, month_end, level="campaign",
    )
    return SpendSummaryResponse(
        last_pull_at=repo.last_pull_at(web.conn, actor.org_id, account_ids),
        data_pulled_at=freshness["data_pulled_at"],
        attribution_label=freshness["attribution_label"],
        campaigns=campaigns,
        total=total,
    )


# ---- 票 past-ads/02：37 個月補拉，一個組織一個背景工作（ADR 0067 §1.8）---------------

class BackfillStartResponse(BaseModel):
    started: bool  # False＝這個組織已經有一個補拉在跑（另一個 lock 相同的 job 還在排隊）
    running: bool  # 起這支端點的意義：不管是不是剛才才起的，回應當下一定是 true


class BackfillOutcome(BaseModel):
    """F50 Contract J（R7 A12）：最近一次補拉怎麼結束的——`background.outcome()` 原樣給。
    `state` running／failed／empty／done；`code`／`text` 是失敗或沒資料的原因。"""
    state: str
    code: str | None
    text: str | None
    finished_at: datetime | None


class BackfillStatusResponse(BaseModel):
    running: bool
    earliest_spend_date: date | None
    latest_spend_date: date | None
    ad_rows: int
    outcome: BackfillOutcome | None  # None＝這個組織從沒排過補拉


@router.post("/brands/{brand_id}/backfill", response_model=BackfillStartResponse)
def start_backfill(request: Request, brand_id: str):
    """啟動這個組織的 37 個月補拉（ADR 0067 §1.8：一個組織一個背景工作，不是一個品牌
    一個——`backfill()` 本身是組織＋廣告帳戶層，見 `daily_pull.backfill` 的 docstring）。
    另一個組織的品牌 → 404，同 `brand_spend`。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    if not repo.bound_account_ids_for_brand(web.conn, actor.org_id, brand_id):
        raise web.ApiError(409, "no_bound_account", "這個品牌還沒綁定 Meta 廣告帳戶。")
    lock = daily_pull.backfill_lock(actor.org_id)
    # `enqueue()` 的 queueing_lock 只擋「還在排隊（todo）」那一段；worker 已經抓走（doing）
    # 的那幾秒再按一次，會多排第二支 37 個月的補拉（結果冪等，只是白跑）。先問 is_active
    # 把 doing 也擋掉——同 app/schedule/routes.py 的 enqueue 呼叫端（review 備註 2026-09-08）。
    if background_is_active(lock):
        return BackfillStartResponse(started=False, running=True)
    started = background_enqueue(daily_pull._BACKFILL_TASK_NAME, org_id=actor.org_id, lock=lock)
    write_audit(
        web.conn, org_id=actor.org_id, brand_id=brand_id, entity_type="meta_backfill",
        entity_id=brand_id, action="start", actor=str(actor.user_id),
    )
    web.conn.commit()
    return BackfillStartResponse(started=started, running=True)


@router.get("/brands/{brand_id}/backfill", response_model=BackfillStatusResponse)
def get_backfill_status(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    account_ids = repo.bound_account_ids_for_brand(web.conn, actor.org_id, brand_id)
    if not account_ids:
        raise web.ApiError(409, "no_bound_account", "這個品牌還沒綁定 Meta 廣告帳戶。")
    status = daily_pull.backfill_status(web.conn, actor.org_id, account_ids)
    lock = daily_pull.backfill_lock(actor.org_id)
    found = background_outcome(lock)
    outcome = (BackfillOutcome(state=found["state"], code=found["code"], text=found["text"],
                               finished_at=found["finished_at"])
               if found is not None else None)
    return BackfillStatusResponse(
        running=background_is_active(lock), outcome=outcome, **status,
    )
