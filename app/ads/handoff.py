"""app/ads/handoff.py — 投放交接包與具名授權（票 8）。

principles 第 19 條：廣告平台發佈初期走人工，自動化只做到「準備好可貼上」的程度。
所以這裡產出的是一頁**照著貼**的清單，不是自動建廣告。

命名、UTM、預算全部由程式產生（決策 0016 硬性原則 4：格式與數字走程式，
LLM 不參與）——命名規則要能被機器再解析回來，交給模型寫只會每期長得不一樣。

安全邊界（鐵則 4）：`activation_authorization.authorized_by` 是 NOT NULL，
沒有具名操作人就建不出授權；`campaign_activation` 必須引用一筆授權才建得起來。
兩者都不由「交接包產好了」或「素材確認了」自動推導——扣板機的是人。
"""

from collections import Counter
from datetime import date
from urllib.parse import quote

from app.ads import account_structure
from app.ads import checklist as ads_checklist
from app.ads import creative as ads_creative
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi
from app.core.audit import write_audit
from app.core.db import DEV_ORG_ID, jsonb, new_id, now_utc

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


def cycle_short_code(cycle: dict) -> str:
    """檔期短碼：跟主題資料夾短碼（`app/ads/theme_engine.py` 的 `folder_code`，
    ADR 0008 第三節「人看得懂的名字在前，四碼短碼在後」）同一種做法——拿高熵 id 的
    尾段當短碼。這裡不生新 id：`cycle["id"]` 本身就是 `new_id("ccy")` 產生的高熵 id，
    重出交接包時取同一個 id 的尾段，短碼才會每次都一樣，不會今天跟明天對不起來。
    """
    return cycle["id"][-4:]


def build_names(brand: dict, cycle: dict, cell: dict, index: int) -> dict:
    """命名建議。格式固定，之後同步回來時才解析得回是哪一期哪一格。

    campaign_name 尾巴多帶檔期短碼（票 22）：utm_campaign 改用 Meta 動態變數
    {{campaign.name}} 之後，系統不再把 cycle id 寫死進網址參數，投手得照這裡建議的
    活動名稱去 Meta 建立，Meta 送廣告時才會把這個名字（含短碼）代回網址，系統才認得回來。
    """
    day = (cycle["start_date"] or date.today()).strftime("%Y%m%d")
    return {
        "campaign_name": f"{_slug(brand['name'])}_{day}_{cycle['objective']}_{cycle_short_code(cycle)}",
        "adset_name": f"{_slug(cell.get('creative_angle') or '')}_{index:02d}",
        "ad_name": f"{_slug(cell.get('creative_angle') or '')}_{index:02d}_ad",
    }


def build_utm(cycle: dict, cell: dict) -> dict:
    """票 22：utm_campaign 改用 Meta 官方動態網址變數（Meta for Developers 建議做法，
    見 `.scratch/creative-studio/issues/22-utm-dynamic-params.md` 背景段的查證），
    值本身就是字面上的 "{{campaign.name}}"——不是 Python 格式化字串，這串文字原封
    不動留在網址裡，由 Meta 在廣告送達時代入投手實際在後台建立的行銷活動名稱。就算
    投手事後在 Meta 後台調整過活動結構，網址參數也會自動跟著走，不像寫死 cycle["id"]
    那樣跟實際脫鉤又無法自動糾正。

    utm_content 保留 cell["id"]，不跟進改成 {{ad.name}}：cell 是系統內部的切角格
    （為什麼買，比較優劣的那一層），不是 Meta 的廣告物件；{{ad.name}} 代進來的是
    投手在 Meta 端實際打的廣告名稱文字，跟這裡要認回「屬於哪個切角」的內部 id 是兩件
    事，套上去只會讓系統認錯，不是「不一致」的問題。
    """
    return {
        "utm_source": "facebook",
        "utm_medium": "paid",
        "utm_campaign": "{{campaign.name}}",
        "utm_content": cell["id"],
    }


_UTM_KEY_ORDER = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")


def utm_query(utm: dict) -> str:
    # safe 多加 {}：utm_campaign 的 Meta 動態變數要以字面 {{...}} 留在網址裡讓 Meta 解析，
    # quote() 預設會把 { } 編碼成 %7B %7D，Meta 就認不出這是動態變數了。
    #
    # BUG 修復（route=C 02-3c，NEW）：utm 這個 dict 常是從 publishing_package.utm_json
    # （jsonb 欄位）讀回來的——Postgres 的 jsonb 儲存格式不保留物件鍵的原始順序（實測
    # SELECT '{"utm_source":"a","utm_medium":"b"}'::jsonb 讀回來變成
    # {"utm_medium": "b", "utm_source": "a"}，依鍵長排序，不是 insertion order），
    # 直接 dict.items() 疊代組出來的網址參數順序不穩定。用固定的正典順序組參數，
    # 不知道的鍵（理論上不該有）照舊排在後面，順序穩定不受讀取來源影響。
    ordered = [(k, utm[k]) for k in _UTM_KEY_ORDER if k in utm]
    ordered += [(k, v) for k, v in utm.items() if k not in _UTM_KEY_ORDER]
    return "&".join(f"{k}={quote(str(v), safe='/{}')}" for k, v in ordered)


def _default_destination(conn, brand_id: str) -> str | None:
    """預設到達網址取品牌自有渠道裡的官網（鐵則 20：AI 拿得到的先填好）。"""
    for channel in bi.list_channels(conn, brand_id):
        if channel.get("channel_type") == "website" and channel.get("identifier"):
            return channel["identifier"]
    return None


def build_packages(conn, brand_id: str, cycle_id: str, actor: str, *, commit: bool = True) -> int:
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
        "DELETE FROM publishing_package WHERE brand_id = %s AND campaign_cycle_id = %s"
        " AND id NOT IN (SELECT publishing_package_id FROM external_ad_mapping"
        "                WHERE publishing_package_id IS NOT NULL)",
        (brand_id, cycle_id),
    )

    ts = now_utc()
    count = 0
    for index, group in enumerate(groups, start=1):
        cell = group["cell"]
        adopted = [v for v in group["variants"] if not v["rejected"]]
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
            "INSERT INTO publishing_package (id, org_id, brand_id, campaign_cycle_id,"
            " experiment_cell_id, product_id, hook_id, copy_variant_id, campaign_name,"
            " adset_name, ad_name, destination_url, utm_json, objective, daily_budget,"
            " status, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'ready', %s)",
            (new_id("pkg"), DEV_ORG_ID, brand_id, cycle_id, cell["id"], product_id,
             hook["id"] if hook else None, copy["id"] if copy else None,
             names["campaign_name"], names["adset_name"], names["ad_name"],
             destination or "", jsonb(utm),
             cycle["objective"], round(daily, 2), ts),
        )
        count += 1

    write_audit(conn, brand_id=brand_id, entity_type="campaign_cycle", entity_id=cycle_id,
                action="build_handoff", actor=actor, before=None, after={"packages": count})
    if commit:
        conn.commit()
    return count


def build_extras(conn, brand_id: str, cycle_id: str) -> dict:
    """交接包擴充欄位（票 10）：CBO／ABO 與組數、轉換事件、歸因視窗、貼文協同指引、檢查清單完成度。

    帳戶結構是 daily_budget 的純函數（見 app/ads/account_structure.py），跟方案選擇頁一樣
    現場算，不落庫——規則卡改過的話，交接包顯示的永遠是目前的門檻，不是產方案當下的舊值。
    """
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    structure = account_structure.recommend(conn, brand_id, ads_repo.derived_plan(cycle)["daily_budget"])
    return {
        "structure": structure,
        "conversion_event": CONVERSION_EVENT_LABEL.get(cycle["objective"], "沒有對應的轉換事件說明。"),
        "attribution_window_setting": ATTRIBUTION_WINDOW_SETTING,
        "attribution_window_explanation": ATTRIBUTION_WINDOW_EXPLANATION,
        "post_coop_note": POST_COOP_NOTE,
        "checklist": ads_checklist.completeness(conn, brand_id, cycle_id),
    }


def has_publishing_package(conn, brand_id: str, cycle_id: str) -> bool:
    """這期是否已經產出過交接包（票 04-angle-rename 決議：產包後切角改名鎖住，這是唯一
    判準——不看 cycle 狀態，因為建包不轉 cycle.status，見 build_handoff_packages()）。"""
    row = conn.execute(
        "SELECT 1 FROM publishing_package WHERE brand_id = %s AND campaign_cycle_id = %s LIMIT 1",
        (brand_id, cycle_id),
    ).fetchone()
    return row is not None


def list_packages(conn, brand_id: str, cycle_id: str) -> list:
    """交接包＋每份要貼的欄位（已組成畫面直接用的樣子）。"""
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM publishing_package WHERE brand_id = %s AND campaign_cycle_id = %s"
        " ORDER BY created_at, id", (brand_id, cycle_id),
    )]
    for row in rows:
        # BUG 修復（route=C 02-3c，NEW）：daily_budget 是 numeric 欄位，讀回來是
        # Decimal；呼叫端（畫面／測試）一律當 float 用（加總、跟 float 相減比較），
        # 讀取端單一收口轉型，同 _with_float_budget 既有模式。
        if row["daily_budget"] is not None:
            row["daily_budget"] = float(row["daily_budget"])
        cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
        utm = row["utm_json"] or {}
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


def _mapping_for(conn, brand_id: str, package_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM external_ad_mapping WHERE brand_id = %s AND publishing_package_id = %s"
        " AND claim_status = 'confirmed'"  # 同步猜的（suggested）列不算「已授權／已建到 Meta」
        " ORDER BY created_at DESC LIMIT 1", (brand_id, package_id),
    ).fetchone()
    return dict(row) if row else None


def report_missing_field(conn, brand_id: str, cycle_id: str, field_key: str, actor: str) -> None:
    """「我找不到這欄位」回報。Meta 介面改版時，這是我們唯一會知道的管道。"""
    write_audit(conn, brand_id=brand_id, entity_type="publishing_package", entity_id=cycle_id,
                action="field_not_found", actor=actor, before=None,
                after={"field": field_key, "label": FIELD_LABELS.get(field_key, field_key)})
    conn.commit()


def go_live(conn, brand_id: str, cycle_id: str, package_id: str, mapping_id: str, *,
           actor: str) -> dict:
    """花錢那一刻才做的三件事（ADR 0019 第 7 條：money moment 是發布，不是建立）：
    1. 建一筆具名的 activation_authorization（誰、何時、授權什麼）。
    2. 建 campaign_activation，引用上面那筆授權。
    3. 整期切 LIVE＋建提醒卡（第 3 天「可以看但別動」、第 7 天與到期日「回填成效」，票 15）。

    兩個呼叫端：`authorize_and_map(..., go_live=True)`（既有手填路徑，手填 ID 本身就代表
    使用者已經在 Meta 手動按過發布）立刻呼叫這支；`app/ads/meta_mcp.py` 的
    `activate_cycle()` 則是每個包真的把 Meta 實體從暫停切成開啟成功後才呼叫，
    失敗的包不會走到這裡、不會有授權列（票 M1-01）。
    """
    package = conn.execute(
        "SELECT * FROM publishing_package WHERE brand_id = %s AND id = %s AND campaign_cycle_id = %s",
        (brand_id, package_id, cycle_id),
    ).fetchone()
    if package is None:
        raise ValueError("找不到這份交接包")
    if not actor:
        raise ValueError("需要具名操作人才能授權投放")

    ts = now_utc()
    auth_id = new_id("ath")
    conn.execute(
        "INSERT INTO activation_authorization (id, org_id, brand_id, scope_type, scope_ref,"
        " authorized_by, authorized_at, note, created_at)"
        " VALUES (%s, %s, %s, 'campaign_activation', %s, %s, %s, %s, %s)",
        (auth_id, DEV_ORG_ID, brand_id, package_id, actor, ts,
         f"確認已在 Meta 開始投放：{package['campaign_name']}", ts),
    )
    conn.execute(
        "INSERT INTO campaign_activation (id, org_id, brand_id, campaign_cycle_id,"
        " external_ad_mapping_id, authorization_id, activated_by, activated_at, created_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (new_id("act"), DEV_ORG_ID, brand_id, cycle_id, mapping_id, auth_id, actor, ts, ts),
    )
    write_audit(conn, brand_id=brand_id, entity_type="campaign_activation", entity_id=mapping_id,
                action="authorize_activation", actor=actor, before=None,
                after={"package_id": package_id, "mapping_id": mapping_id})
    conn.commit()

    if ads_repo.get_cycle(conn, brand_id, cycle_id)["status"] != "LIVE":
        ads_repo.update_cycle_status(conn, brand_id, cycle_id, status="LIVE", actor=actor)

    from app.ads import onboarding
    onboarding.create_reminders(conn, brand_id, cycle_id)
    return {"authorization_id": auth_id}


# authorize_and_map() 的 go_live 參數會蓋掉同名的模組層函式——留一個內部別名，讓函式
# 本體照樣叫得到 go_live()（Python 參數在函式作用域內一律蓋過同名的模組層名稱）。
_go_live = go_live


def authorize_and_map(conn, brand_id: str, cycle_id: str, package_id: str, *,
                      meta_ids: dict, actor: str, go_live: bool = True) -> dict:
    """回填 Meta ID（＋預設立刻具名授權發布，見上面的 go_live()）。

    go_live=True（既有手填路徑，行為不變）：回填 external_ad_mapping 後立刻視為
    「已經在 Meta 開始投放」，呼叫 go_live() 建授權＋切 LIVE＋建提醒卡——手填 ID
    這件事本身就代表使用者已經在 Meta 手動按過發布了。

    go_live=False（票 M1-01：`app/ads/meta_mcp.py` 的 create_package() 用）：Meta 端
    建的是暫停物件，這時候還沒開始花錢（ADR 0019 第 7 條），只回填 mapping，不建授權、
    不切 LIVE、不建提醒卡——那些留給 activate_cycle() 真的把 Meta 實體切成開啟後才做。

    ADR 0004 起 require_actor 一律回傳固定值，不會再是空字串；這裡的 `if not actor` 是給
    繞過路由層、直接呼叫本函式的呼叫端（例如測試）留的第二道保險，不是操作人攔截。
    """
    package = conn.execute(
        "SELECT * FROM publishing_package WHERE brand_id = %s AND id = %s AND campaign_cycle_id = %s",
        (brand_id, package_id, cycle_id),
    ).fetchone()
    if package is None:
        raise ValueError("找不到這份交接包")
    if not (meta_ids.get("meta_campaign_id") or "").strip():
        raise ValueError("請至少填入行銷活動 ID，系統才對得上成效數字")
    if not actor:
        raise ValueError("需要具名操作人才能授權投放")

    # 上線前校驗不符只提醒不擋（ADR 0006，取代已作廢的 0025 補遺第 7 點鎖住規則）——
    # 警示由畫面顯示（見 app/ads/codes.verification_warning），這裡不再讀校驗結果。

    ts = now_utc()
    account_id = (meta_ids.get("meta_account_id") or "").strip() or None
    ad_account_id = _ensure_ad_account(conn, account_id, ts) if account_id else None

    mapping_id = new_id("xam")
    conn.execute(
        "INSERT INTO external_ad_mapping (id, org_id, brand_id, publishing_package_id,"
        " campaign_cycle_id, ad_account_id, platform, meta_account_id, meta_campaign_id,"
        " meta_adset_id, meta_ad_id, meta_creative_id, claim_status, confirmed_by,"
        " confirmed_at, created_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, 'meta', %s, %s, %s, %s, %s, 'confirmed', %s, %s, %s)",
        (mapping_id, DEV_ORG_ID, brand_id, package_id, cycle_id, ad_account_id, account_id,
         (meta_ids.get("meta_campaign_id") or "").strip(),
         (meta_ids.get("meta_adset_id") or "").strip() or None,
         (meta_ids.get("meta_ad_id") or "").strip() or None,
         (meta_ids.get("meta_creative_id") or "").strip() or None,
         actor, ts, ts),
    )

    if ad_account_id:
        conn.execute("UPDATE campaign_cycle SET ad_account_id = %s WHERE brand_id = %s AND id = %s",
                     (ad_account_id, brand_id, cycle_id))
    conn.commit()

    if not go_live:
        return {"authorization_id": None, "mapping_id": mapping_id}

    result = _go_live(conn, brand_id, cycle_id, package_id, mapping_id, actor=actor)
    return {"authorization_id": result["authorization_id"], "mapping_id": mapping_id}


# ---------------------------------------------------------------------------
# 命名與 UTM 檢查（票 B4R-warroom-redesign，S8.28-29／廣告強化第 3 項）：純函數，
# 不改動 build_names()／build_utm() 本身，只比對已產出的交接包。
# ---------------------------------------------------------------------------

def naming_check(conn, brand_id: str, cycle_id: str, packages: list) -> dict:
    """S8.28（B4R 收尾修正）：`adset_name`／`ad_name` 一定要逐份互不相同、無空字串——
    這兩個名字靠 `build_names()`（:93-105）的 index 分開，撞名代表真的出錯。

    `campaign_name` 不同：`build_names()` 本來就是一檔期一活動名，底下每個切角共用
    同一個名字（`build_packages()`：165-170 重出交接包時還會留下已授權的舊包，同檔期內
    自然會有更多份共用同一個名字），同檔期內重複是設計如此、不算撞名。真正該擋的是
    「同品牌、不同檔期」不小心撞出同一個活動名稱（檔期短碼理論上不會撞，這顆檢查是防萬一）。
    """
    duplicates, missing = [], []
    for field in ("campaign_name", "adset_name", "ad_name"):
        seen: dict = {}
        for pkg in packages:
            value = pkg.get(field) or ""
            if not value:
                missing.append({"package_id": pkg["id"], "field": field})
                continue
            seen.setdefault(value, []).append(pkg["id"])
        if field == "campaign_name":
            continue  # 同檔期本就共用一個活動名，不比對同檔期內部
        for value, ids in seen.items():
            if len(ids) > 1:
                duplicates.append({"field": field, "value": value, "package_ids": ids})

    names = {pkg.get("campaign_name") for pkg in packages if pkg.get("campaign_name")}
    if names:
        placeholders = ",".join(["%s"] * len(names))
        rows = conn.execute(
            "SELECT id, campaign_name FROM publishing_package WHERE brand_id = %s"
            f" AND campaign_cycle_id != %s AND campaign_name IN ({placeholders})",
            (brand_id, cycle_id, *names),
        ).fetchall()
        other_ids_by_name: dict = {}
        for row in rows:
            other_ids_by_name.setdefault(row["campaign_name"], []).append(row["id"])
        for value, other_ids in other_ids_by_name.items():
            own_ids = [pkg["id"] for pkg in packages if pkg.get("campaign_name") == value]
            duplicates.append({"field": "campaign_name", "value": value,
                               "package_ids": own_ids + other_ids})

    return {"duplicates": duplicates, "missing": missing, "passed": not duplicates and not missing}


# UTM 官方標準共 5 個經典參數，本系統刻意不使用 utm_term（來源：Google Analytics 官方說明
# support.google.com/analytics/answer/10917952，查證日 2026-08-12）——utm_term 官方定義是
# 「付費關鍵字」，Meta 是興趣／受眾投放不是關鍵字搜尋廣告，沒有對應概念可填。
_UTM_REQUIRED = ("utm_source", "utm_medium", "utm_campaign", "utm_content")
_UTM_NOT_APPLICABLE = {
    "utm_term": "本系統投放對象是 Meta 興趣／受眾投放，不是關鍵字搜尋廣告，"
                "沒有對應的付費關鍵字概念可填（不適用，非搜尋型廣告）。",
}


def utm_check(packages: list) -> list:
    """S8.29：確認四個既有 UTM 參數皆非空，逐份交接包各回一筆。"""
    from urllib.parse import parse_qs
    results = []
    for pkg in packages:
        params = parse_qs(pkg.get("utm_text") or "")
        present = [k for k in _UTM_REQUIRED if params.get(k) and params[k][0]]
        results.append({
            "package_id": pkg["id"], "present": present,
            "not_applicable": [{"param": k, "reason": v} for k, v in _UTM_NOT_APPLICABLE.items()],
            "passed": len(present) == len(_UTM_REQUIRED),
        })
    return results


# ---------------------------------------------------------------------------
# 交接總分環（票 B4R-warroom-redesign，S8R.13-17）：純聚合既有三組使用者自行勾選狀態＋
# 本節新增的命名／UTM 檢查通過與否，不重算任何判定邏輯（同 S8.59 compile_closing_review()
# 的聚合手法）。
# ---------------------------------------------------------------------------

def readiness_ring(conn, brand_id: str, cycle_id: str) -> dict:
    """`fix_anchor` 逐值對照前端實際渲染的容器 id（一次性＋每期必看合渲在同一張卡片
    `id="checklist-block"`，見 `ChecklistSection.tsx:27`；命名／UTM 檢查共卡
    `id="naming-utm-block"`，見 `NamingUtmSection.tsx:20`；QA 五項 `id="qa-launch-block"`，
    見 `QaAutoCheckSection.tsx:32`）——前端不改，後端錨點對齊前端既有 id，不是隨意命名。"""
    items = []
    for item in ads_checklist.one_time_status(conn, brand_id):
        items.append({"key": item["key"], "label": item["label"], "passed": item["checked"],
                      "section": "one_time_checklist", "fix_anchor": "checklist-block"})
    for item in ads_checklist.cycle_status(conn, brand_id, cycle_id):
        items.append({"key": item["key"], "label": item["label"], "passed": item["checked"],
                      "section": "cycle_checklist", "fix_anchor": "checklist-block"})

    packages = list_packages(conn, brand_id, cycle_id)
    naming = naming_check(conn, brand_id, cycle_id, packages)
    items.append({"key": "naming_check", "label": "命名檢查（無撞名、無缺漏）",
                  "passed": naming["passed"], "section": "naming_check",
                  "fix_anchor": "naming-utm-block"})
    utm_results = utm_check(packages)
    utm_passed = all(r["passed"] for r in utm_results) if utm_results else True
    items.append({"key": "utm_check", "label": "UTM 檢查（四參數皆非空）", "passed": utm_passed,
                  "section": "utm_check", "fix_anchor": "naming-utm-block"})

    for item in ads_checklist.qa_launch_status(conn, brand_id):
        items.append({"key": item["key"], "label": item["label"], "passed": item["checked"],
                      "section": "qa_launch", "fix_anchor": "qa-launch-block"})

    items.sort(key=lambda i: i["passed"])  # 未過項排最前（False < True）
    return {"passed": sum(1 for i in items if i["passed"]), "total": len(items), "items": items}


def _ensure_ad_account(conn, external_account_id: str, ts: str) -> str:
    """廣告帳號不綁品牌（一個帳號可服務多品牌，決策 0022 第 6 點），有就取、沒有就建。"""
    row = conn.execute(
        "SELECT id FROM ad_account WHERE platform = 'meta' AND external_account_id = %s",
        (external_account_id,),
    ).fetchone()
    if row:
        return row["id"]
    account_id = new_id("adc")
    conn.execute(
        "INSERT INTO ad_account (id, org_id, platform, external_account_id, status, created_at,"
        " updated_at) VALUES (%s, %s, 'meta', %s, 'active', %s, %s)",
        (account_id, DEV_ORG_ID, external_account_id, ts, ts),
    )
    return account_id
