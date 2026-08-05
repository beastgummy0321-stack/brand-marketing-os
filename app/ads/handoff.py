# -*- coding: utf-8 -*-
"""app/ads/handoff.py — 投放交接包與具名授權（票 8）。

principles 第 19 條：廣告平台發佈初期走人工，自動化只做到「準備好可貼上」的程度。
所以這裡產出的是一頁**照著貼**的清單，不是自動建廣告。

命名、UTM、預算全部由程式產生（決策 0016 硬性原則 4：格式與數字走程式，
LLM 不參與）——命名規則要能被機器再解析回來，交給模型寫只會每期長得不一樣。

安全邊界（鐵則 4）：`activation_authorization.authorized_by` 是 NOT NULL，
沒有具名操作人就建不出授權；`campaign_activation` 必須引用一筆授權才建得起來。
兩者都不由「交接包產好了」或「素材確認了」自動推導——扣板機的是人。
"""

import json
from collections import Counter
from datetime import date
from typing import Optional
from urllib.parse import quote

from app.ads import account_structure
from app.ads import checklist as ads_checklist
from app.ads import codes as ads_codes
from app.ads import creative as ads_creative
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi
from app.core.audit import write_audit
from app.core.db import new_id, now_iso

OBJECTIVE_META_LABEL = {
    "awareness": "品牌知名度",
    "traffic": "流量",
    "engagement": "互動",
    "leads": "潛在客戶開發",
    "sales": "銷售（轉換）",
}

# 交接包擴充（票 10）：每個成效目標對應的轉換事件白話說明。格式與數字走程式，
# 這裡只是固定對照表，不是 AI 判斷（決策 0016 硬性原則 4）。
CONVERSION_EVENT_LABEL = {
    "awareness": "不用設定轉換事件——這個目標優化的是觸及與曝光，不是特定動作。",
    "traffic": "連結點擊（依廣告管理員選的優化方式，可能是 Landing Page View 或 Link Click）。",
    "engagement": "互動（貼文互動或訊息），通常不需要另外設 Pixel 轉換事件。",
    "leads": "名單完成（用 Meta 內建表單）或網站上對應的「完成註冊」事件。",
    "sales": "購買（Purchase）——用 Pixel 或 Conversions API 回報的購買事件。",
}

# Meta 目前的預設歸因設定。這裡固定顯示這個值＋白話解釋，不是可調參數——
# 使用者在 Meta 後台自己改掉的話，交接包會提醒回來對一下（見 attribution_window()）。
ATTRIBUTION_WINDOW_SETTING = "7 天點擊、1 天瀏覽（Meta 目前的預設值）"
ATTRIBUTION_WINDOW_EXPLANATION = (
    "意思是：使用者點了廣告後 7 天內、或看到廣告後 1 天內完成的轉換，都算這支廣告帶來的。"
    "如果你在 Meta 廣告管理員把這個設定改掉，系統看到的轉換數字跟 Meta 後台可能會對不起來，"
    "不是系統算錯——記得回來核對一下用的是不是同一個歸因視窗。"
)

POST_COOP_NOTE = (
    "同一份素材如果要開在不同廣告組測試，記得在 Meta 廣告管理員用「使用現有貼文」，"
    "讓這幾組共用同一則貼文，而不是各自重新發一則——這樣按讚、留言、分享的互動數才會"
    "累積在同一則貼文上，不會被拆散到好幾則各自很少互動的貼文，也有助於壓低單次曝光成本（CPM）。"
)

# Meta 廣告管理員現行的欄位名稱（鐵則 12：用使用者在畫面上看得到的字，不用內部代號）。
# Meta 介面改版時只改這裡；配合「我找不到這欄位」回報鈕，改版才追得上。
FIELD_LABELS = {
    "campaign_name": "行銷活動名稱",
    "objective": "行銷活動目標",
    "adset_name": "廣告組合名稱",
    "daily_budget": "每日預算",
    "schedule": "排程",
    "destination_url": "網站網址",
    "ad_name": "廣告名稱",
    "primary_text": "主要文字",
    "headline": "標題",
    "utm": "網址參數",
}


def _slug(text: str, limit: int = 20) -> str:
    """命名用的短片段：去掉會讓 Meta 命名難讀的符號，留中文與英數。"""
    cleaned = "".join(ch for ch in (text or "") if ch.isalnum() or ch in "－-_")
    return cleaned[:limit] or "未命名"


def build_names(brand: dict, cycle: dict, cell: dict, index: int) -> dict:
    """命名建議。格式固定，之後同步回來時才解析得回是哪一期哪一格。"""
    day = (cycle["start_date"] or date.today().isoformat()).replace("-", "")
    return {
        "campaign_name": f"{_slug(brand['name'])}_{day}_{cycle['objective']}",
        "adset_name": f"{_slug(cell.get('creative_angle') or '')}_{index:02d}",
        "ad_name": f"{_slug(cell.get('creative_angle') or '')}_{index:02d}_ad",
    }


def build_utm(cycle: dict, cell: dict) -> dict:
    return {
        "utm_source": "facebook",
        "utm_medium": "paid",
        "utm_campaign": cycle["id"],
        "utm_content": cell["id"],
    }


def utm_query(utm: dict) -> str:
    return "&".join(f"{k}={quote(str(v))}" for k, v in utm.items())


def _default_destination(conn, brand_id: str) -> Optional[str]:
    """預設到達網址取品牌自有渠道裡的官網（鐵則 20：AI 拿得到的先填好）。"""
    for channel in bi.list_channels(conn, brand_id):
        if channel.get("channel_type") == "website" and channel.get("identifier"):
            return channel["identifier"]
    return None


def build_packages(conn, brand_id: str, cycle_id: str, actor: str) -> int:
    """依採用的素材，每個切角產一份交接包。回傳份數。

    重跑會整批換掉——素材改過就該重出，不留舊版交接包讓人貼錯。
    """
    brand = bi.get_brand(conn, brand_id)
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if brand is None or cycle is None:
        raise ValueError("找不到品牌或廣告檔期")

    plan = ads_repo.derived_plan(cycle)
    allocations = {a["product_id"]: a for a in
                   ads_repo.list_cycle_products(conn, brand_id, cycle_id)}
    destination = _default_destination(conn, brand_id)
    groups = ads_creative.group_by_cell(conn, brand_id, cycle_id)
    # 一個產品可能配多個切角（DEFAULT_ANGLE_COUNT，預設 4），該產品的預算要先除以
    # 底下的切角數，每個切角組合才不會各自拿到整個產品的日預算（修憲落地 M1，
    # bug：漏了這一除，交接包貼進 Meta 後實際日花費是計畫的切角數倍）。
    product_angle_counts = Counter(
        g["cell"].get("product_id") for g in groups if g["cell"].get("product_id")
    )

    conn.execute(
        "DELETE FROM publishing_package WHERE brand_id = ? AND campaign_cycle_id = ?"
        " AND id NOT IN (SELECT publishing_package_id FROM external_ad_mapping"
        "                WHERE publishing_package_id IS NOT NULL)",
        (brand_id, cycle_id),
    )

    ts = now_iso()
    count = 0
    for index, group in enumerate(groups, start=1):
        cell = group["cell"]
        # 野路子實驗組（票 6a／#57）不參與「這個切角唯一一支正式廣告」的選取——
        # 它 recommendation_rank 固定是 0（見 creative.py _generate_wildcard_variant），
        # 若不排除會被下面的 next() 優先選中，讓刻意踩禁區的內容取代正常 Hook 貼進交接包。
        # 法務掃描（compliance.scan_cycle）走 list_variants，不受這裡影響，行為不變。
        adopted = [v for v in group["variants"]
                   if not v["rejected"] and not v.get("experiment_variant")]
        if not adopted:
            continue

        names = build_names(brand, cycle, cell, index)
        utm = build_utm(cycle, cell)
        hook = next((v for v in adopted if v["variant_type"] == "hook"), None)
        copy = next((v for v in adopted if v["variant_type"] == "copy"), None)

        # 各切角的每日預算：該產品的分配額除以天數、再除以該產品底下的切角數；
        # 沒綁產品就用整期日預算除以切角數
        product_id = cell.get("product_id")
        days = plan.get("duration_days") or 1
        if product_id and product_id in allocations:
            angle_count = max(product_angle_counts.get(product_id, 1), 1)
            daily = allocations[product_id]["allocated_budget"] / days / angle_count
        else:
            daily = (cycle["budget"] or 0) / days / max(len(groups), 1)

        conn.execute(
            "INSERT INTO publishing_package (id, brand_id, campaign_cycle_id,"
            " experiment_cell_id, product_id, hook_id, copy_variant_id, campaign_name,"
            " adset_name, ad_name, destination_url, utm_json, objective, daily_budget,"
            " status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?)",
            (new_id("pkg"), brand_id, cycle_id, cell["id"], product_id,
             hook["id"] if hook else None, copy["id"] if copy else None,
             names["campaign_name"], names["adset_name"], names["ad_name"],
             destination or "", json.dumps(utm, ensure_ascii=False),
             cycle["objective"], round(daily, 2), ts),
        )
        count += 1

    write_audit(conn, brand_id=brand_id, entity_type="campaign_cycle", entity_id=cycle_id,
                action="build_handoff", actor=actor, before=None, after={"packages": count})
    conn.commit()
    return count


def build_extras(conn, brand_id: str, cycle_id: str) -> dict:
    """交接包擴充欄位（票 10）：CBO／ABO 與組數、轉換事件、歸因視窗、貼文協同指引、檢查清單完成度。

    帳戶結構是 daily_budget 的純函數（見 app/ads/account_structure.py），跟方案選擇頁一樣
    現場算，不落庫——規則卡改過的話，交接包顯示的永遠是目前的門檻，不是產方案當下的舊值。
    """
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    structure = account_structure.recommend(conn, ads_repo.derived_plan(cycle)["daily_budget"])
    return {
        "structure": structure,
        "conversion_event": CONVERSION_EVENT_LABEL.get(cycle["objective"], "沒有對應的轉換事件說明。"),
        "attribution_window_setting": ATTRIBUTION_WINDOW_SETTING,
        "attribution_window_explanation": ATTRIBUTION_WINDOW_EXPLANATION,
        "post_coop_note": POST_COOP_NOTE,
        "checklist": ads_checklist.completeness(conn, brand_id, cycle_id),
    }


def list_packages(conn, brand_id: str, cycle_id: str) -> list:
    """交接包＋每份要貼的欄位（已組成畫面直接用的樣子）。"""
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM publishing_package WHERE brand_id = ? AND campaign_cycle_id = ?"
        " ORDER BY created_at, id", (brand_id, cycle_id),
    )]
    for row in rows:
        cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
        utm = json.loads(row["utm_json"] or "{}")
        url = row["destination_url"] or ""
        row["full_url"] = f"{url}{'&' if '?' in url else '?'}{utm_query(utm)}" if url else ""
        row["utm_text"] = utm_query(utm)
        row["schedule_text"] = f"{cycle['start_date']} 到 {cycle['end_date']}"
        row["objective_label"] = OBJECTIVE_META_LABEL.get(row["objective"], row["objective"])

        variants = {}
        for key, field in (("hook_id", "hook"), ("copy_variant_id", "copy")):
            if row[key]:
                variant = ads_creative.get_variant(conn, brand_id, row[key])
                variants[field] = variant["content"] if variant else ""
        row["hook_text"] = variants.get("hook", "")
        row["copy_text"] = variants.get("copy", "")

        cell_variants = [v for v in ads_creative.list_variants(conn, brand_id, cycle_id)
                         if v["experiment_cell_id"] == row["experiment_cell_id"]
                         and v["variant_type"] == "image_prompt" and not v["rejected"]]
        row["image_prompts"] = [v["content"] for v in cell_variants]

        row["mapping"] = _mapping_for(conn, brand_id, row["id"])
    return rows


def _mapping_for(conn, brand_id: str, package_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM external_ad_mapping WHERE brand_id = ? AND publishing_package_id = ?"
        " ORDER BY created_at DESC LIMIT 1", (brand_id, package_id),
    ).fetchone()
    return dict(row) if row else None


def report_missing_field(conn, brand_id: str, cycle_id: str, field_key: str, actor: str) -> None:
    """「我找不到這欄位」回報。Meta 介面改版時，這是我們唯一會知道的管道。"""
    write_audit(conn, brand_id=brand_id, entity_type="publishing_package", entity_id=cycle_id,
                action="field_not_found", actor=actor, before=None,
                after={"field": field_key, "label": FIELD_LABELS.get(field_key, field_key)})
    conn.commit()


def authorize_and_map(conn, brand_id: str, cycle_id: str, package_id: str, *,
                      meta_ids: dict, actor: str) -> dict:
    """關卡三：具名投放授權＋回填 Meta ID。

    這一步同時做三件事，缺一不可：
    1. 建一筆具名的 activation_authorization（誰、何時、授權什麼）。
    2. 建 external_ad_mapping（人工回填的直接算 confirmed 歸屬）。
    3. 建 campaign_activation，必須引用上面那筆授權。

    ADR 0004 起 require_actor 一律回傳固定值，不會再是空字串；這裡的 `if not actor` 是給
    繞過路由層、直接呼叫本函式的呼叫端（例如測試）留的第二道保險，不是操作人攔截。
    """
    package = conn.execute(
        "SELECT * FROM publishing_package WHERE brand_id = ? AND id = ? AND campaign_cycle_id = ?",
        (brand_id, package_id, cycle_id),
    ).fetchone()
    if package is None:
        raise ValueError("找不到這份交接包")
    if not (meta_ids.get("meta_campaign_id") or "").strip():
        raise ValueError("請至少填入行銷活動 ID，系統才對得上成效數字")
    if not actor:
        raise ValueError("需要具名操作人才能授權投放")

    # 上線前校驗不符時只鎖這一期的開跑動作（GitHub issue #35，決策 0025 補遺第 7 點），
    # 不影響其他任何流程；沒校驗過不鎖，校驗過且不符才鎖。
    lock_reason = ads_codes.is_activation_locked(conn, brand_id, cycle_id)
    if lock_reason:
        raise ValueError(lock_reason)

    ts = now_iso()
    auth_id = new_id("ath")
    conn.execute(
        "INSERT INTO activation_authorization (id, brand_id, scope_type, scope_ref,"
        " authorized_by, authorized_at, note, created_at)"
        " VALUES (?, ?, 'campaign_activation', ?, ?, ?, ?, ?)",
        (auth_id, brand_id, package_id, actor, ts,
         f"確認已在 Meta 開始投放：{package['campaign_name']}", ts),
    )

    account_id = (meta_ids.get("meta_account_id") or "").strip() or None
    ad_account_id = _ensure_ad_account(conn, account_id, ts) if account_id else None

    mapping_id = new_id("xam")
    conn.execute(
        "INSERT INTO external_ad_mapping (id, brand_id, publishing_package_id,"
        " campaign_cycle_id, ad_account_id, platform, meta_account_id, meta_campaign_id,"
        " meta_adset_id, meta_ad_id, meta_creative_id, claim_status, confirmed_by,"
        " confirmed_at, created_at)"
        " VALUES (?, ?, ?, ?, ?, 'meta', ?, ?, ?, ?, ?, 'confirmed', ?, ?, ?)",
        (mapping_id, brand_id, package_id, cycle_id, ad_account_id, account_id,
         (meta_ids.get("meta_campaign_id") or "").strip(),
         (meta_ids.get("meta_adset_id") or "").strip() or None,
         (meta_ids.get("meta_ad_id") or "").strip() or None,
         (meta_ids.get("meta_creative_id") or "").strip() or None,
         actor, ts, ts),
    )

    conn.execute(
        "INSERT INTO campaign_activation (id, brand_id, campaign_cycle_id,"
        " external_ad_mapping_id, authorization_id, activated_by, activated_at, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (new_id("act"), brand_id, cycle_id, mapping_id, auth_id, actor, ts, ts),
    )

    if ad_account_id:
        conn.execute("UPDATE campaign_cycle SET ad_account_id = ? WHERE brand_id = ? AND id = ?",
                     (ad_account_id, brand_id, cycle_id))

    write_audit(conn, brand_id=brand_id, entity_type="campaign_activation", entity_id=mapping_id,
                action="authorize_activation", actor=actor, before=None,
                after={"package_id": package_id, "meta_ids": meta_ids})
    conn.commit()

    if ads_repo.get_cycle(conn, brand_id, cycle_id)["status"] != "LIVE":
        ads_repo.update_cycle_status(conn, brand_id, cycle_id, status="LIVE", actor=actor)

    # 開始投放才建提醒卡：第 3 天「可以看但別動」、第 7 天與到期日「回填成效」（票 15）
    from app.ads import onboarding
    onboarding.create_reminders(conn, brand_id, cycle_id)
    return {"authorization_id": auth_id, "mapping_id": mapping_id}


def _ensure_ad_account(conn, external_account_id: str, ts: str) -> str:
    """廣告帳號不綁品牌（一個帳號可服務多品牌，決策 0022 第 6 點），有就取、沒有就建。"""
    row = conn.execute(
        "SELECT id FROM ad_account WHERE platform = 'meta' AND external_account_id = ?",
        (external_account_id,),
    ).fetchone()
    if row:
        return row["id"]
    account_id = new_id("adc")
    conn.execute(
        "INSERT INTO ad_account (id, platform, external_account_id, status, created_at,"
        " updated_at) VALUES (?, 'meta', ?, 'active', ?, ?)",
        (account_id, external_account_id, ts, ts),
    )
    return account_id
