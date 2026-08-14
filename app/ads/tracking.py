# -*- coding: utf-8 -*-
"""R5/R6 追蹤鏈：短碼建議、靜態檢查與上線 72 小時後三方對照。"""

from datetime import date
from typing import Optional
from urllib import request as urlrequest

from app.ads import codes as ads_codes
from app.ads import ga4_sync
from app.ads import handoff as ads_handoff
from app.ads import performance as ads_performance
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import interrupts as core_interrupts
from app.core import net
from app.core.db import new_id, now_iso

# 第 7 刀（A1 三層地界新規則：app/ads 不得 import app.orders，見
# test_architecture_boundaries.py）：orders_channel 不在這裡 import，改由組裝根
# app/main.py 啟動時注入真正的 app.orders.channel 模組（品牌層追蹤健檢——票 T0——
# 蝦皮／藥局「曾匯入過」要查 app.orders 的表，同 app/ads/reading.py 既有寫法）。
orders_channel = None

POST_LAUNCH_CHECK_DAYS = 3
_PAID_MEDIA = {"paid", "paid_social", "cpc", "ppc"}


def probe_url(url: str) -> bool:
    """只驗到達頁能否打開；內容是否正確仍由人確認。"""
    if not url:
        return False
    try:
        req = urlrequest.Request(url, method="HEAD")
        with urlrequest.urlopen(req, timeout=5) as response:
            return 200 <= response.status < 300
    except Exception:  # noqa: BLE001 — 網站不可達一律收斂成紅燈
        return False


def _discovered(conn, ad_account_id: str, meta_campaign_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM discovered_campaign WHERE ad_account_id = ? AND meta_campaign_id = ?",
        (ad_account_id, meta_campaign_id),
    ).fetchone()
    return dict(row) if row else None


def _campaign_owner(conn, ad_account_id: str, meta_campaign_id: str) -> tuple:
    row = conn.execute(
        "SELECT brand_id, campaign_cycle_id FROM external_ad_mapping"
        " WHERE meta_campaign_id = ? ORDER BY (claim_status = 'confirmed') DESC, created_at DESC"
        " LIMIT 1", (meta_campaign_id,),
    ).fetchone()
    if row:
        return row["brand_id"], row["campaign_cycle_id"]
    discovered = _discovered(conn, ad_account_id, meta_campaign_id)
    if not discovered:
        return None, None
    return discovered["claimed_brand_id"] or discovered["suggested_brand_id"], None


def alert_campaign_renamed(conn, ad_account_id: str, meta_campaign_id: str,
                           old_name: str, new_name: str) -> None:
    if not old_name or old_name == new_name:
        return
    brand_id, cycle_id = _campaign_owner(conn, ad_account_id, meta_campaign_id)
    if not brand_id:
        return
    core_interrupts.enqueue(
        conn, category="campaign_renamed",
        dedupe_key=f"campaign_renamed:{meta_campaign_id}:{new_name}",
        brand_id=brand_id, campaign_cycle_id=cycle_id,
        message="Meta 活動名稱被改了，請確認追蹤。",
        action_url=f"/brands/{brand_id}/ads/connections",
    )


def _short_code(campaign_name: str) -> Optional[str]:
    tail = (campaign_name or "").rsplit("_", 1)[-1]
    return tail if len(tail) == 4 and tail.isalnum() else None


def _remove_suggestion(conn, meta_campaign_id: str) -> None:
    conn.execute(
        "DELETE FROM external_ad_mapping WHERE meta_campaign_id = ? AND claim_status = 'suggested'",
        (meta_campaign_id,),
    )


def suggest_cycle_mapping(conn, ad_account_id: str, meta_account_id: str,
                          meta_campaign_id: str) -> Optional[str]:
    """依活動名稱尾四碼寫入既有 external_ad_mapping 的 suggested 態。"""
    discovered = _discovered(conn, ad_account_id, meta_campaign_id)
    if not discovered:
        return None
    brand_id = discovered["claimed_brand_id"] or discovered["suggested_brand_id"]
    code = _short_code(discovered["campaign_name"] or "")
    if not brand_id or not code:
        _remove_suggestion(conn, meta_campaign_id)
        return None

    matches = [dict(row) for row in conn.execute(
        "SELECT * FROM campaign_cycle WHERE brand_id = ? AND substr(id, -4) = ?",
        (brand_id, code),
    )]
    if len(matches) != 1:
        _remove_suggestion(conn, meta_campaign_id)
        if len(matches) > 1:
            core_interrupts.enqueue(
                conn, category="tracking_broken",
                dedupe_key=f"tracking_conflict:{brand_id}:{meta_campaign_id}:{code}",
                brand_id=brand_id, message="同一活動跨兩期，請補廣告 ID。",
                action_url=f"/brands/{brand_id}/ads/connections",
            )
        return "conflict" if matches else None

    cycle_id = matches[0]["id"]
    other_cycle = conn.execute(
        "SELECT campaign_cycle_id FROM external_ad_mapping WHERE meta_campaign_id = ?"
        " AND claim_status = 'confirmed' AND campaign_cycle_id <> ? LIMIT 1",
        (meta_campaign_id, cycle_id),
    ).fetchone()
    if other_cycle:
        _remove_suggestion(conn, meta_campaign_id)
        core_interrupts.enqueue(
            conn, category="tracking_broken",
            dedupe_key=f"tracking_conflict:{brand_id}:{meta_campaign_id}:{cycle_id}",
            brand_id=brand_id, message="同一活動跨兩期，請補廣告 ID。",
            action_url=f"/brands/{brand_id}/ads/connections",
        )
        return "conflict"
    confirmed = conn.execute(
        "SELECT 1 FROM external_ad_mapping WHERE brand_id = ? AND campaign_cycle_id = ?"
        " AND meta_campaign_id = ? AND claim_status = 'confirmed' LIMIT 1",
        (brand_id, cycle_id, meta_campaign_id),
    ).fetchone()
    if confirmed:
        _remove_suggestion(conn, meta_campaign_id)
        return "confirmed"

    package = conn.execute(
        "SELECT id FROM publishing_package WHERE brand_id = ? AND campaign_cycle_id = ?"
        " ORDER BY created_at, id LIMIT 1", (brand_id, cycle_id),
    ).fetchone()
    existing = conn.execute(
        "SELECT id FROM external_ad_mapping WHERE meta_campaign_id = ?"
        " AND claim_status = 'suggested' LIMIT 1", (meta_campaign_id,),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE external_ad_mapping SET brand_id = ?, publishing_package_id = ?,"
            " campaign_cycle_id = ?, ad_account_id = ?, meta_account_id = ? WHERE id = ?",
            (brand_id, package["id"] if package else None, cycle_id, ad_account_id,
             meta_account_id, existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO external_ad_mapping (id, brand_id, publishing_package_id,"
            " campaign_cycle_id, ad_account_id, platform, meta_account_id, meta_campaign_id,"
            " claim_status, created_at) VALUES (?, ?, ?, ?, ?, 'meta', ?, ?, 'suggested', ?)",
            (new_id("xam"), brand_id, package["id"] if package else None, cycle_id,
             ad_account_id, meta_account_id, meta_campaign_id, now_iso()),
        )
    return "suggested"


def alert_unmapped_spend(conn, ad_account_id: str, meta_campaign_id: str,
                         spend: float, as_of_date: str) -> None:
    if spend <= 0:
        return
    brand_id, _cycle_id = _campaign_owner(conn, ad_account_id, meta_campaign_id)
    amount = f"{spend:,.0f}"
    core_interrupts.enqueue(
        conn, category="burn_no_cycle",
        dedupe_key=f"burn_no_cycle:{meta_campaign_id}:{as_of_date}",
        brand_id=brand_id, message=f"NT${amount} 廣告花費沒對應檔期。",
        action_url=(f"/brands/{brand_id}/ads/connections" if brand_id else "/settings"),
    )


def _mapping_rows(conn, brand_id: str, cycle_id: str) -> tuple:
    rows = [dict(row) for row in conn.execute(
        "SELECT * FROM external_ad_mapping WHERE brand_id = ? AND campaign_cycle_id = ?"
        " ORDER BY created_at DESC", (brand_id, cycle_id),
    )]
    return ([r for r in rows if r["claim_status"] == "confirmed"],
            [r for r in rows if r["claim_status"] == "suggested"])


def _actual_campaigns(conn, mappings: list) -> list:
    ids = {m["meta_campaign_id"] for m in mappings if m.get("meta_campaign_id")}
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    return [dict(row) for row in conn.execute(
        f"SELECT * FROM discovered_campaign WHERE meta_campaign_id IN ({placeholders})", tuple(ids),
    )]


def _node(status: str, message: str, action: str) -> dict:
    return {"status": status, "message": message, "action": action}


def _naming_node(cycle: dict, packages: list, campaigns: list) -> tuple:
    if not campaigns:
        return _node("yellow", "同步後才能核對 Meta 活動名稱。", "立刻更新"), False
    expected_names = {p["campaign_name"] for p in packages}
    wrong_name = any(c.get("campaign_name") not in expected_names for c in campaigns)
    wrong_objective = any(c.get("objective") and c["objective"] != cycle["objective"]
                          for c in campaigns)
    if wrong_name or wrong_objective:
        reason = "活動目標與企劃不一致。" if wrong_objective else "Meta 活動名稱已和交接包不同。"
        return _node("red", reason, "查看命名檢查"), False
    return _node("green", "Meta 活動名稱與企劃目標都對上。", "查看命名檢查"), True


def _paid_ga4_rows(conn, brand_id: str) -> list:
    return [row for row in ga4_sync.latest_summary(conn, brand_id)
            if (row.get("medium") or "").lower() in _PAID_MEDIA]


def _post_launch_node(conn, brand_id: str, cycle: dict, static_ok: bool, today: str) -> dict:
    if not static_ok:
        return _node("red", "到達頁、UTM 或活動目標有一項沒對上。", "查看檢查清單")
    if (date.fromisoformat(today) - date.fromisoformat(cycle["start_date"])).days < POST_LAUNCH_CHECK_DAYS:
        return _node("green", "上線前檢查通過，滿 72 小時再交叉驗證。", "查看檢查清單")

    totals = ads_performance.totals(conn, brand_id, cycle["id"])
    paid_rows = _paid_ga4_rows(conn, brand_id)
    meta_clicks = totals["clicks"] or 0
    meta_conversions = totals["conversions"] or 0
    ga4_sessions = sum(row["sessions"] or 0 for row in paid_rows)
    ga4_conversions = sum(row["conversions"] or 0 for row in paid_rows)
    code_uses = ads_codes.attribution_summary(conn, brand_id, cycle["id"])["gross"]["count"]
    if meta_clicks and not ga4_sessions:
        return _node("red", "Meta 有點擊，但 GA4 沒收到付費流量。", "查看檢查清單")
    if ga4_sessions and not meta_clicks:
        return _node("red", "GA4 有付費流量，但 Meta 沒有點擊。", "查看檢查清單")
    if (meta_conversions or ga4_conversions) and not code_uses:
        return _node("red", "平台有轉換，但訂單配碼沒有動靜。", "查看配碼")
    if not meta_clicks and not ga4_sessions:
        return _node("yellow", "滿 72 小時仍沒有足夠流量可核對。", "立刻更新")
    return _node("green", "Meta、GA4 與訂單配碼訊號對得上。", "查看檢查清單")


def tracking_chain(conn, brand_id: str, cycle_id: str, *, today: Optional[str] = None,
                   url_probe=None) -> dict:
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if not cycle:
        raise ValueError("找不到廣告檔期")
    today = today or date.today().isoformat()
    url_probe = url_probe or probe_url
    packages = ads_handoff.list_packages(conn, brand_id, cycle_id)
    confirmed, suggested = _mapping_rows(conn, brand_id, cycle_id)
    campaigns = _actual_campaigns(conn, confirmed or suggested)
    naming, objective_ok = _naming_node(cycle, packages, campaigns)

    if confirmed:
        mapping = _node("green", "Meta 活動已確認對應到這期。", "查看交接包")
    elif suggested and suggested[0].get("publishing_package_id"):
        mapping = _node("yellow", "偵測到短碼對應，等你確認。", "確認對應")
    elif suggested:
        mapping = _node("yellow", "已找到檔期，先產交接包再確認。", "產出交接包")
    else:
        mapping = _node("red", "找不到自動對應，請貼上 Meta 活動 ID。", "查看交接包")

    code_rows = ads_codes.list_codes(conn, brand_id, cycle_id)
    codes = (_node("green", "廣告碼與口播碼已建立。", "查看配碼") if code_rows else
             _node("red", "這期還沒有建立配碼。", "建立配碼"))
    utm_ok = bool(packages) and all(r["passed"] for r in ads_handoff.utm_check(packages))
    urls_ok = bool(packages) and all(url_probe(p.get("destination_url") or "") for p in packages)
    landing = _post_launch_node(conn, brand_id, cycle, utm_ok and urls_ok and objective_ok, today)
    return {"naming": naming, "mapping": mapping, "codes": codes, "landing_utm": landing}


def confirm_suggested_mapping(conn, brand_id: str, cycle_id: str, actor: str) -> dict:
    suggestion = conn.execute(
        "SELECT * FROM external_ad_mapping WHERE brand_id = ? AND campaign_cycle_id = ?"
        " AND claim_status = 'suggested' ORDER BY created_at DESC LIMIT 1",
        (brand_id, cycle_id),
    ).fetchone()
    if not suggestion:
        raise ValueError("目前沒有可確認的自動對應")
    package_id = suggestion["publishing_package_id"]
    if not package_id:
        raise ValueError("先產出交接包，才能確認這筆對應")
    return ads_handoff.authorize_and_map(
        conn, brand_id, cycle_id, package_id,
        meta_ids={"meta_campaign_id": suggestion["meta_campaign_id"],
                  "meta_account_id": suggestion["meta_account_id"]},
        actor=actor,
    )


def run_post_sync_checks(conn, brand_id: str, *, today: Optional[str] = None,
                         url_probe=None) -> int:
    today = today or date.today().isoformat()
    created = 0
    for cycle in ads_repo.list_cycles(conn, brand_id):
        if cycle["status"] not in ("LIVE", "EVALUATING"):
            continue
        node = tracking_chain(
            conn, brand_id, cycle["id"], today=today, url_probe=url_probe)["landing_utm"]
        if node["status"] != "red":
            continue
        interrupt_id = core_interrupts.enqueue(
            conn, category="tracking_broken",
            dedupe_key=f"tracking_broken:{cycle['id']}:{node['message']}",
            brand_id=brand_id, campaign_cycle_id=cycle["id"], message=node["message"][:30],
            action_url=f"/brands/{brand_id}/ads/{cycle['id']}",
        )
        created += bool(interrupt_id)
    conn.commit()
    return created


# ---------------------------------------------------------------------------
# 品牌層追蹤健檢（票 T0，契約 1.1-1.8／2.1／2.4／2.6）：五張通路卡就緒狀態。跟上面
# R5/R6 檔期層追蹤鏈是兩件事——那邊管一期廣告的追蹤鏈，這裡管品牌整體五路（官網／FB／
# IG／蝦皮／藥局）有沒有把追蹤基本功裝好，供健檢頁與安裝精靈用。
# ---------------------------------------------------------------------------

TRACKING_CHANNEL_KEYS = ("website", "fb_page", "ig_account", "shopee", "pharmacy")

# GA4／Meta Pixel 安裝特徵字串（官方文件查證，票 T0 契約 1.3）：
#   GA4：script src 含 googletagmanager.com/gtag/js 且頁面含 gtag('config'
#     （來源：https://developers.google.com/tag-platform/gtagjs）
#   Meta Pixel：script src 含 connect.facebook.net/en_US/fbevents.js 且含 fbq('init'
#     （來源：https://developers.facebook.com/docs/meta-pixel/get-started）
_GA4_SCRIPT_MARK = "googletagmanager.com/gtag/js"
_GA4_CONFIG_MARK = "gtag('config'"
_PIXEL_SCRIPT_MARK = "connect.facebook.net/en_US/fbevents.js"
_PIXEL_INIT_MARK = "fbq('init'"


def _detect_ga4(raw_html: str) -> bool:
    return _GA4_SCRIPT_MARK in raw_html and _GA4_CONFIG_MARK in raw_html


def _detect_pixel(raw_html: str) -> bool:
    return _PIXEL_SCRIPT_MARK in raw_html and _PIXEL_INIT_MARK in raw_html


def _tracking_check_row(conn, brand_id: str, channel_key: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM channel_tracking_check WHERE brand_id = ? AND channel_key = ?",
        (brand_id, channel_key),
    ).fetchone()
    return dict(row) if row else None


def _hidden(conn, brand_id: str, channel_key: str) -> bool:
    row = _tracking_check_row(conn, brand_id, channel_key)
    return bool(row and row["hidden"])


def set_channel_hidden(conn, brand_id: str, channel_key: str, hidden: bool) -> None:
    """通路卡「用不到」旗標（契約 1.2：可收合、可恢復）。"""
    if channel_key not in TRACKING_CHANNEL_KEYS:
        raise ValueError(f"不認得的通路：{channel_key}")
    conn.execute(
        "INSERT INTO channel_tracking_check (brand_id, channel_key, hidden) VALUES (?, ?, ?)"
        " ON CONFLICT(brand_id, channel_key) DO UPDATE SET hidden = excluded.hidden",
        (brand_id, channel_key, int(bool(hidden))),
    )
    conn.commit()


def _save_website_check(conn, brand_id: str, *, ga4_found: bool, pixel_found: bool, checked_at: str) -> None:
    conn.execute(
        "INSERT INTO channel_tracking_check (brand_id, channel_key, ga4_found, pixel_found, checked_at)"
        " VALUES (?, 'website', ?, ?, ?)"
        " ON CONFLICT(brand_id, channel_key) DO UPDATE SET"
        " ga4_found = excluded.ga4_found, pixel_found = excluded.pixel_found,"
        " checked_at = excluded.checked_at",
        (brand_id, int(ga4_found), int(pixel_found), checked_at),
    )
    conn.commit()


def _website_url(conn, brand_id: str) -> Optional[str]:
    for channel in bi_repo.list_channels(conn, brand_id):
        if channel.get("channel_type") == "website" and channel.get("identifier"):
            return channel["identifier"]
    return None


def _website_node(conn, brand_id: str, url: Optional[str]) -> dict:
    hidden = _hidden(conn, brand_id, "website")
    if not url:
        return {"key": "website", "status": "off", "sub": None, "checked_at": None, "hidden": hidden,
                "message": "還沒有填官網網址，先去品牌資料填。",
                "action": {"kind": "fill", "missing": []}}
    row = _tracking_check_row(conn, brand_id, "website")
    checked_at = row["checked_at"] if row else None
    if checked_at is None:
        return {"key": "website", "status": "bad", "sub": url, "checked_at": None, "hidden": hidden,
                "message": "還沒檢查過，按「重新檢查全部」試試看。",
                "action": {"kind": "install", "missing": ["ga4", "pixel"]}}
    missing = [name for name, found in (("ga4", row["ga4_found"]), ("pixel", row["pixel_found"]))
              if not found]
    if not missing:
        status, message = "ok", "GA4 和 Meta Pixel 都偵測到了。"
    elif missing == ["pixel"]:
        status, message = "warn", "GA4 偵測到了，Meta Pixel 還沒偵測到。"
    elif missing == ["ga4"]:
        status, message = "warn", "Meta Pixel 偵測到了，GA4 還沒偵測到。"
    else:
        status, message = "bad", "GA4 和 Meta Pixel 都還沒偵測到。"
    action = {"kind": "none", "missing": []} if status == "ok" else {"kind": "install", "missing": missing}
    return {"key": "website", "status": status, "sub": url, "checked_at": checked_at, "hidden": hidden,
            "message": message, "action": action}


def check_website_now(conn, brand_id: str, *, fetch=None) -> dict:
    """官網 GA4／Pixel 偵測：立刻抓一次，寫回 channel_tracking_check，回官網那張卡。
    給精靈頁 2.4「我裝好了，幫我檢查」單獨呼叫，也給「重新檢查全部」背景工作呼叫——
    同一份邏輯，不分岔成兩條路徑。抓不到頁面／找不到特徵字串一律當作沒裝，不拋例外
    （契約 2.4：失敗不擋人）。"""
    fetch = fetch or net.fetch_raw_html
    url = _website_url(conn, brand_id)
    if url:
        ok, raw_html = fetch(url)
        ga4_found = _detect_ga4(raw_html) if ok else False
        pixel_found = _detect_pixel(raw_html) if ok else False
        _save_website_check(conn, brand_id, ga4_found=ga4_found, pixel_found=pixel_found,
                            checked_at=now_iso())
    return _website_node(conn, brand_id, url)


_IDENTIFIER_LABELS = {"fb_page": "FB 粉專", "ig_account": "IG 帳號"}


def _identifier_node(conn, brand_id: str, channel_key: str, identifier: Optional[str]) -> dict:
    hidden = _hidden(conn, brand_id, channel_key)
    label = _IDENTIFIER_LABELS[channel_key]
    if identifier:
        return {"key": channel_key, "status": "ok", "sub": identifier, "checked_at": None, "hidden": hidden,
                "message": f"已經填了{label}，可以追蹤成效。", "action": {"kind": "none", "missing": []}}
    return {"key": channel_key, "status": "off", "sub": None, "checked_at": None, "hidden": hidden,
            "message": f"還沒填{label}，先去品牌資料填。", "action": {"kind": "fill", "missing": []}}


_IMPORT_LABELS = {"shopee": "蝦皮", "pharmacy": "藥局"}


def _import_node(conn, brand_id: str, channel_key: str, last_date: Optional[str]) -> dict:
    hidden = _hidden(conn, brand_id, channel_key)
    label = _IMPORT_LABELS[channel_key]
    if last_date:
        return {"key": channel_key, "status": "ok", "sub": last_date, "checked_at": None, "hidden": hidden,
                "message": f"曾經匯入過{label}資料，最近一次 {last_date}。",
                "action": {"kind": "none", "missing": []}}
    return {"key": channel_key, "status": "off", "sub": None, "checked_at": None, "hidden": hidden,
            "message": f"還沒有匯入過{label}資料。", "action": {"kind": "fill", "missing": []}}


def tracking_health(conn, brand_id: str) -> dict:
    """五張通路卡就緒狀態彙總（契約 1.1-1.8）：官網／FB／IG 讀 owned_channel（品牌永久層，
    只走 bi_repo.list_channels 公開函式）；蝦皮／藥局讀有沒有匯入過（app.ads 不得 import
    app.orders，改由 app/main.py 注入 orders_channel，見檔頭「第 7 刀」同款寫法）。
    ready／total 只算未隱藏（hidden=False）的卡（契約 1.1）。"""
    owned_by_type: dict = {}
    for channel in bi_repo.list_channels(conn, brand_id):
        ct = channel.get("channel_type")
        if ct in ("website", "fb_page", "ig_account") and ct not in owned_by_type:
            owned_by_type[ct] = channel

    website = owned_by_type.get("website") or {}
    fb_page = owned_by_type.get("fb_page") or {}
    ig_account = owned_by_type.get("ig_account") or {}

    channels = [
        _website_node(conn, brand_id, website.get("identifier") or None),
        _identifier_node(conn, brand_id, "fb_page", fb_page.get("identifier") or None),
        _identifier_node(conn, brand_id, "ig_account", ig_account.get("identifier") or None),
        _import_node(conn, brand_id, "shopee", orders_channel.shopee_latest_import(conn, brand_id)),
        _import_node(conn, brand_id, "pharmacy", orders_channel.pharmacy_latest_batch(conn, brand_id)),
    ]
    visible = [c for c in channels if not c["hidden"]]
    ready = sum(1 for c in visible if c["status"] == "ok")
    return {"channels": channels, "ready": ready, "total": len(visible)}
