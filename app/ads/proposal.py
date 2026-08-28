"""T3 提案書聚合與核可。

對外進入點：proposal()、approve()、return_to_opening()、seed_channel_plans()。
輸入輸出：收 SQLite 連線、品牌與檔期識別值，回傳凍結的提案 dict 或寫入後的 dict。
誰依賴它：僅 routes_campaigns_open_api.py 經提案書 API 呼叫。
不碰什麼：不 import orders、dashboard，不修改 ads repository 或 reading，也不呼叫 LLM。
"""


from app.ads import onboarding, pacing_curve, theme_repository, tracking
from app.ads import plan as ads_plan
from app.ads import repository as ads_repo
from app.ads import repository_channel_plan as channel_repo
from app.brand_intelligence import repository as bi
from app.core import orchestrator as core_orchestrator
from app.core import rule_cards
from app.core.db import Conn, jsonb, new_id, now_utc

# 開檔後的五類預設分工。現階段只有 Meta 真正投放，其他項目誠實保留為待辦或健檢。
_CHANNEL_DEFAULTS = {
    "social": {
        "job": "用 Meta 把人帶到主要購買頁", "pct": 100,
        "expected": "讓更多合適的人看見並前往購買頁", "depth": "full",
    },
    "google_search": {
        "job": "整理搜尋用語與廣告文案", "pct": 0,
        "expected": "準備好需要時可啟用的搜尋素材", "depth": "task_card",
    },
    "line_email": {
        "job": "準備熟客週訊內容", "pct": 0,
        "expected": "讓既有客人知道本期主打內容", "depth": "task_card",
    },
    "kol_media": {
        "job": "整理合作名單與聯繫重點", "pct": 0,
        "expected": "準備可執行的合作邀請", "depth": "task_card",
    },
    "website_landing": {
        "job": "檢查購買頁的到達與追蹤", "pct": 0,
        "expected": "確認客人能順利到達購買頁", "depth": "healthcheck",
    },
}


def seed_channel_plans(conn: Conn, brand_id: str, cycle_id: str) -> list:
    """在既有開檔路徑補齊五類管道，沿用上一期的用／不用選擇。"""
    if channel_repo.list_channel_plans(conn, brand_id, cycle_id):
        return channel_repo.list_channel_plans(conn, brand_id, cycle_id)
    previous_enabled = channel_repo.previous_enabled_defaults(conn, brand_id, cycle_id)
    for channel in channel_repo.CHANNELS:
        defaults = _CHANNEL_DEFAULTS[channel]
        channel_repo.create_channel_plan(
            conn, brand_id, cycle_id, channel=channel, job=defaults["job"], pct=defaults["pct"],
            expected=defaults["expected"], enabled=previous_enabled.get(channel, True),
            depth=defaults["depth"],
        )
    return channel_repo.list_channel_plans(conn, brand_id, cycle_id)


def proposal(conn: Conn, brand_id: str, cycle_id: str) -> dict:
    """同步組裝六區塊；任何既有資料來源失敗都收斂成人話 failed 狀態。"""
    try:
        plan = ads_plan.get_latest_plan(conn, brand_id, cycle_id)
        if plan is None:
            return {"status": "assembling", "reason": None, "blocks": {}, "approval": {}}
        cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
        if cycle is None:
            raise ValueError("找不到這一期資料")
        derived = ads_repo.derived_plan(cycle)
        tracking_summary = tracking.tracking_health(conn, brand_id)
        budget = {"budget": cycle["budget"], "allocations": ads_repo.list_cycle_products(conn, brand_id, cycle_id)}
        forecast = onboarding.forecast_snapshot(cycle)
        if forecast:
            budget["forecast"] = (
                f"這期大約可帶來 {forecast['clicks_low']} 到 {forecast['clicks_high']} 次前往，"
                f"並完成 {forecast['conversions_low']} 到 {forecast['conversions_high']} 筆訂單。"
            )
        creatives = []
        cells = conn.execute(
            "SELECT id FROM experiment_cell WHERE brand_id = %s AND campaign_cycle_id = %s ORDER BY id",
            (brand_id, cycle_id),
        ).fetchall()
        for cell in cells:
            creatives.extend(theme_repository.list_themes_for_cell(conn, brand_id, cell["id"]))
        daily_stop_loss = float(derived.get("daily_stop_loss") or 0)
        pause_spend = float(derived.get("pause_threshold_spend") or 0)
        deviation = rule_cards.get_value(conn, brand_id, "pacing", "deviation_threshold_ratio")
        fatigue = rule_cards.get_value(conn, brand_id, "ad_creative_fatigue", "cold_warning")
        brakes = [
            f"每天花費超過 NT${daily_stop_loss:,.0f} 時會提醒你查看。",
            f"花費累計到 NT${pause_spend:,.0f} 還沒有結果，會建議先暫停檢查。",
            f"花費進度與時間進度相差超過 {deviation:.0%}，或同一則素材重複被看到約 {fatigue:g} 次時會提醒調整。",
        ]
        strategy = pacing_curve.STRATEGIES.get(derived.get("pacing_strategy") or "", {})
        strategy_text = strategy.get("desc") or "先依目前步調進行"
        schedule = (
            f"{cycle['start_date']} 開跑，共 {derived.get('duration_days')} 天；"
            f"前 3 到 7 天先讓系統學習，不急著調整。{strategy_text}。"
        )
        has_red = any(channel.get("status") == "bad" for channel in tracking_summary["channels"])
        return {
            "status": "ready", "reason": None,
            "blocks": {
                "channels": channel_repo.list_channel_plans(conn, brand_id, cycle_id),
                "budget": budget,
                "creatives": creatives,
                "tracking": tracking_summary,
                "brakes": brakes,
                "schedule": schedule,
            },
            "approval": {
                "approved": plan["status"] == "approved",
                "warning": "追蹤有紅燈，仍可核可；建議盡快完成安裝或檢查。" if has_red else None,
            },
        }
    except Exception:  # noqa: BLE001 — 提案書讀取失敗不應掉成 500
        return {
            "status": "failed", "reason": "提案書暫時整理不出來，資料都還在，請稍後再試。",
            "blocks": {}, "approval": {},
        }


def approve(conn: Conn, brand_id: str, cycle_id: str, actor: str) -> list:
    """核可既有計畫，並把核可當下的提案快照、天花板與任務卡落成同一交易。"""
    org_id = bi.get_brand(conn, brand_id)["org_id"]
    plan = ads_plan.get_latest_plan(conn, brand_id, cycle_id)
    if plan is None:
        raise ValueError("這期還沒有計畫可以確認")
    assembled = proposal(conn, brand_id, cycle_id)
    if assembled["status"] != "ready":
        raise ValueError(assembled["reason"] or "提案書還在整理，請稍後再試。")
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if cycle is None:
        raise ValueError("找不到這一期資料")
    plans = channel_repo.list_channel_plans(conn, brand_id, cycle_id)
    payload = dict(plan["plan"])
    payload.setdefault("proposal_snapshot", {
        "channels": assembled["blocks"]["channels"],
        "budget": assembled["blocks"]["budget"],
        "brakes": assembled["blocks"]["brakes"],
        "schedule": assembled["blocks"]["schedule"],
    })
    ts = now_utc()
    cards = []
    conn.execute("BEGIN")
    try:
        conn.execute(
            "UPDATE campaign_plan SET plan_json = %s WHERE id = %s",
            (jsonb(payload), plan["id"]),
        )
        # budget 是開檔已確認的既有天花板欄位；核可時和任務卡一起再落一次。
        conn.execute(
            "UPDATE campaign_cycle SET budget = %s, updated_at = %s WHERE brand_id = %s AND id = %s",
            (cycle["budget"], ts, brand_id, cycle_id),
        )
        conn.execute(
            "DELETE FROM task_card WHERE brand_id = %s AND cycle_id = %s AND channel != 'social'",
            (brand_id, cycle_id),
        )
        for channel in plans:
            if not channel["enabled"] or channel["channel"] == "social":
                continue
            card = {
                "id": new_id("tsk"), "org_id": org_id, "brand_id": brand_id, "cycle_id": cycle_id,
                # ponytail: draft_hint 保留給 quick-generate 接手；此處只建卡，不預先填寫草稿。
                "channel": channel["channel"], "title": channel["job"], "draft_hint": None,
                # BUG 修復（route=C 02-3c，app/ads/proposal.py:169）：done 是 boolean 欄
                # 位，綁參數傳整數 0 一樣是型別不符（DatatypeMismatch），SQLite 沒差是
                # 因為沒有真正的 boolean 型別。
                "done": False, "created_at": ts, "done_at": None,
            }
            conn.execute(
                "INSERT INTO task_card (id, org_id, brand_id, cycle_id, channel, title, draft_hint, done, created_at, done_at)"
                " VALUES (%(id)s, %(org_id)s, %(brand_id)s, %(cycle_id)s, %(channel)s, %(title)s, %(draft_hint)s,"
                " %(done)s, %(created_at)s, %(done_at)s)",
                card,
            )
            cards.append(card)
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()
    ads_plan.approve(conn, brand_id, cycle_id, actor)
    return cards


def return_to_opening(conn: Conn, brand_id: str, cycle_id: str, actor: str) -> None:
    """退回開檔調整，不動既有計畫與開檔原值。"""
    ads_repo.update_cycle_status(conn, brand_id, cycle_id, status="PLANNING", actor=actor)


# ---------------------------------------------------------------------------
# 調度台『提案』模組門面（票 O1-02，ADR 0024）
# ---------------------------------------------------------------------------

def _current_cycle(conn, brand_id: str) -> "dict | None":
    """比照 app/ads/diagnosis.py:29 _current_cycle()：取最新一個投放中或等判讀的檔期。
    不 import weekly_proposals.current_cycle()（會拉進 nextcycle／reading 一整串）。"""
    for cycle in ads_repo.list_cycles(conn, brand_id):
        if cycle["status"] in ("LIVE", "EVALUATING"):
            return cycle
    return None


def status(conn, brand_id: str) -> dict:
    """調度台 facts：`proposal.cycle_id`、`proposal.plan_ready`（這期有沒有計畫可核可）、
    `proposal.approved`（最新一版計畫核可了沒）。不呼叫 proposal()——那支要組六區塊，
    每輪跑代價過高（票 O1-02 明文）。"""
    cycle = _current_cycle(conn, brand_id)
    if cycle is None:
        return {"proposal.cycle_id": None, "proposal.plan_ready": False,
                "proposal.approved": False}
    plan = ads_plan.get_latest_plan(conn, brand_id, cycle["id"])
    return {
        "proposal.cycle_id": cycle["id"],
        "proposal.plan_ready": plan is not None,
        "proposal.approved": plan is not None and plan["status"] == "approved",
    }


def handle(conn, action: dict) -> dict:
    """提案模組沒有任何 op：核可是使用者關卡②（ADR 0018），不得自動化；其餘進入點都是
    唯讀或人按。收到任何 op 一律丟 ValueError（ADR 0024 決議 6）。"""
    raise ValueError(f"提案模組不認得這個 op：{action['op']}")


core_orchestrator.register_module("proposal", status=status, handle=handle)
