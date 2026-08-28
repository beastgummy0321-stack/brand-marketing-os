"""app/ads/qa_autocheck.py — 上線前 QA 五項提醒的系統覆核（票 Q1-01，補完 ADR 0016 §1「日後升級」）。

2026-08-24 對使用者真實帳號 368741390835357 實測，證實五項全部讀得到，所以這裡把原本
「技術上做不到系統覆核」的四項（Pixel／受眾排除／CAPI EMQ／預算覆核）全部改成真的打
Meta 查。到達頁實點測試維持原樣（`_probe_url`，從 `routes_campaigns_handoff_api.py` 搬過來，
邏輯不變）。

唯一進入點：`results(conn, brand_id, cycle_id) -> list[dict]`，回傳形狀跟改版前一樣
（`AutoCheckResult`，前端型別不變）。呼叫端只有 `routes_campaigns_handoff_api.py` 兩支路由：
`qa_auto_check()` 與 `readiness()`——`handoff.readiness_ring()` 不呼叫本檔（它只純聚合，
合併「系統驗過也算過」是在路由層做的），依賴方向永遠只有 qa_autocheck → handoff。

錯誤不穿牆（container-contract）：每一支對外呼叫都包 try，失敗一律轉成
`available=False` 加白話理由，不讓例外爬到路由層。
"""

import json
import re
import time
from datetime import date

from app.ads import checklist as ads_checklist
from app.ads import handoff as ads_handoff
from app.ads import meta_mcp

# ponytail: 60s in-process cache, per-request if staleness ever bites —
# `/qa-auto-check` 跟 `/readiness` 幾乎同時載入，同一個 (brand_id, cycle_id) 60 秒內
# 不重打 Meta。快取只蓋「Meta 讀回來的部分」；使用者自行勾選的 `checked` 每次都重讀
# （brand_checklist_item 隨時可能被使用者按掉，快取住就會顯示過期狀態）。
_CACHE_TTL_SECONDS = 60
_cache: dict = {}

_PIXEL_FRESH_DAYS = 7  # Meta EMQ 官方文件（見 QA_LAUNCH_ITEMS 旁連結）只給比對窗口 48 小時，
# 沒給「多久沒開火算掛了」的官方門檻；沿用 app/ads/tracking.py:_PIXEL_FRESH_DAYS 同款
# 「7 天內有開火就算活著」的既有判準，不另訂一個新數字。

_ADSET_FIELDS = ["id", "name", "campaign_id", "daily_budget", "targeting"]
_CAMPAIGN_FIELDS = ["id", "daily_budget"]


def _available(key: str, label: str, passed: bool, note: str) -> dict:
    return {"key": key, "label": label, "available": True, "passed": passed,
            "checked": False, "note": note}


def _unavailable(key: str, label: str, note: str) -> dict:
    return {"key": key, "label": label, "available": False, "passed": None,
            "checked": False, "note": note}


def _probe_url(url: str) -> bool:
    """輕量到達頁探測（S8.34，從 routes_campaigns_handoff_api.py 搬過來，邏輯不變）：
    HEAD 只看回應碼是否 2xx，抓不到「內容對不對」。"""
    if not url:
        return False
    import urllib.request
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return 200 <= resp.status < 300
    except Exception:  # noqa: BLE001 — 探測失敗一律算沒過，不讓例外傳上去
        return False


# ---------------------------------------------------------------------------
# 共用的 Meta 讀取：資料集（Pixel 已裝／CAPI EMQ 共用同一次 ads_get_datasets）、
# 廣告組合配對（受眾排除／預算覆核共用同一次配對結果）。
# ---------------------------------------------------------------------------

def _fetch_datasets(account_id: str) -> "tuple[list, str | None]":
    try:
        result = meta_mcp.call_tool("ads_get_datasets", {"ad_account_id": account_id})
    except Exception as exc:  # noqa: BLE001 — 對外呼叫一律不穿牆
        return [], meta_mcp.plain_error(exc)
    return result.get("datasets") or [], None


def _dedupe_datasets(datasets: list) -> dict:
    """同一個 dataset_id 會重複出現，重複列可能帶 `1969-12-31T16:00:00-0800`（epoch 0）——
    每個 id 只留 `last_fired_time` 字串最大（=最新）的那一列，不能信第一筆。"""
    best: dict = {}
    for d in datasets:
        did = d.get("dataset_id")
        if not did:
            continue
        current = str(d.get("last_fired_time") or "")
        kept = str(best[did].get("last_fired_time") or "") if did in best else ""
        if did not in best or current > kept:
            best[did] = d
    return best


def _fetch_entities(account_id: str, level: str, fields: list) -> "tuple[list, str | None]":
    try:
        result = meta_mcp.call_tool("ads_get_ad_entities",
                                    {"ad_account_id": account_id, "level": level, "fields": fields})
    except Exception as exc:  # noqa: BLE001
        return [], meta_mcp.plain_error(exc)
    raw = result.get("ad_entities")  # 注意：這是 JSON 字串，不是 list（票面 Gotcha）。
    if not raw:
        return [], None
    try:
        return json.loads(raw), None
    except (TypeError, ValueError):
        return [], "Meta 回傳的廣告組合資料格式讀不出來。"


def _match_adsets(conn, brand_id: str, cycle_id: str, packages: list,
                  account_id: str) -> "tuple[list, str | None]":
    """把交接包配對到 Meta 的廣告組合（配對規則見票面「Matching packages to Meta adsets」）：
    有 `external_ad_mapping` 就先用那批 `meta_campaign_id` 縮小範圍，再一律用
    `adset_name` 精準配對——`handoff.naming_check()` 已保證這個名字帳號內不撞名，不用另外
    處理同名歧義。回傳 `([(package, adset), ...], 錯誤白話或 None)`；配不到任何一組回空
    list（呼叫端一律當 available=false 處理，不區分「沒交接包」跟「配不到」兩種原因）。"""
    if not packages:
        return [], None
    adsets, err = _fetch_entities(account_id, "adset", _ADSET_FIELDS)
    if err is not None:
        return [], err
    campaign_ids = {r["meta_campaign_id"] for r in conn.execute(
        "SELECT DISTINCT meta_campaign_id FROM external_ad_mapping WHERE brand_id = %s"
        " AND campaign_cycle_id = %s AND meta_campaign_id IS NOT NULL AND meta_campaign_id != ''",
        (brand_id, cycle_id)).fetchall()}
    if campaign_ids:
        # ponytail: mapping 裡的 campaign_id 若已失效（活動被刪、或當初填錯帳號），這裡會
        # 縮到空集合，結果就是回報「還沒在 Meta 找到這期的廣告組合」而不退回純名字配對。
        # 2026-08-24 實測確認這是誠實答案（那期本來就沒建到這個帳號），先不加退路；
        # 真的遇到「ID 過期但名字還在」再改成篩完是空的就不篩。
        adsets = [a for a in adsets if a.get("campaign_id") in campaign_ids]
    by_name = {a["name"]: a for a in adsets if a.get("name")}
    pairs = [(pkg, by_name[pkg["adset_name"]]) for pkg in packages if pkg.get("adset_name") in by_name]
    return pairs, None


# ---------------------------------------------------------------------------
# 五項檢查本體
# ---------------------------------------------------------------------------

def _pixel_check(conn, brand_id: str, datasets: list, fetch_err: str | None) -> dict:
    key, label = "qa_pixel_installed", "Pixel 已正確安裝"
    if fetch_err is not None:
        return _unavailable(key, label, f"讀不到 Meta 的 Pixel 清單：{fetch_err}")
    today = date.today()
    fresh = False
    for d in _dedupe_datasets(datasets).values():
        if not d.get("is_active"):
            continue
        fired_date = str(d.get("last_fired_time") or "")[:10]
        try:
            if fired_date and (today - date.fromisoformat(fired_date)).days <= _PIXEL_FRESH_DAYS:
                fresh = True
                break
        except ValueError:
            continue
    if not fresh:
        return _available(key, label, False,
                          f"沒看到 {_PIXEL_FRESH_DAYS} 天內還在回報事件的啟用中 Pixel，"
                          "去 Meta 事件管理工具確認安裝狀態。")
    anomaly = ads_checklist.pixel_anomaly(conn, brand_id)
    if anomaly:
        return _available(key, label, False, anomaly)
    return _available(key, label, True, "你的 Pixel 最近還在正常回報事件。")


def _emq_check(datasets: list, fetch_err: str | None) -> dict:
    key, label = "qa_capi_emq_quality", "CAPI／EMQ 事件品質已確認"
    if fetch_err is not None:
        return _unavailable(key, label, f"讀不到 Meta 的 Pixel 清單：{fetch_err}")
    active = [d for d in _dedupe_datasets(datasets).values() if d.get("is_active")]
    if not active:
        return _unavailable(key, label, "沒有啟用中的 Pixel，還沒辦法查事件比對品質。")
    active.sort(key=lambda d: str(d.get("last_fired_time") or ""), reverse=True)
    dataset_id = active[0]["dataset_id"]
    try:
        result = meta_mcp.call_tool("ads_get_dataset_quality",
                                    {"dataset_id": dataset_id, "query_type": ["web"]})
    except Exception as exc:  # noqa: BLE001
        return _unavailable(key, label, f"讀不到事件比對品質：{meta_mcp.plain_error(exc)}")
    events = result.get("web") or []
    # 決策 2：只認「有沒有分數」，分數本身不印、不訂門檻——Meta 官方文件只給 0-10 尺度
    # 跟 48 小時窗口，沒公布及格線，使用者也明講不想被分數打擾。
    has_score = any((e.get("event_match_quality") or {}).get("composite_score") is not None
                    for e in events)
    if has_score:
        return _available(key, label, True, "CAPI 有事件回報比對品質分數，代表伺服器端事件有送達並比對成功。")
    return _available(key, label, False, "CAPI 事件目前都還沒有比對品質分數，可能是送達量太少或還沒開始送，"
                      "去 Meta 事件管理工具確認。")


def _audience_exclusion_check(pairs: list, match_err: str | None) -> dict:
    key, label = "qa_audience_exclusion", "受眾排除名單已設定"
    if match_err is not None:
        return _unavailable(key, label, f"讀不到 Meta 的廣告組合：{match_err}")
    if not pairs:
        return _unavailable(key, label, "還沒在 Meta 找到這期的廣告組合。")
    offenders = [pkg.get("adset_name") or adset.get("name") or "" for pkg, adset in pairs
                if not (adset.get("targeting") or {}).get("excluded_custom_audiences")]
    if not offenders:
        return _available(key, label, True, "每組廣告組合都設定了排除受眾。")
    extra = f"（還有 {len(offenders) - 1} 組也沒設）" if len(offenders) > 1 else ""
    return _available(key, label, False, f"「{offenders[0]}」沒有設定排除受眾。{extra}")


def _parse_budget(raw) -> int | None:
    """Meta 回的預算是顯示格式化字串，例如「NT$2,143 TWD」——去掉非數字字元後轉整數
    （票面 Gotcha）。缺欄位回 None（呼叫端自行決定要不要退回活動層預算）。"""
    if raw is None:
        return None
    digits = re.sub(r"[^0-9]", "", str(raw))
    return int(digits) if digits else None


def _budget_check(pairs: list, match_err: str | None, account_id: str) -> dict:
    key, label = "qa_budget_line_review", "預算已逐筆覆核"
    if match_err is not None:
        return _unavailable(key, label, f"讀不到 Meta 的廣告組合：{match_err}")
    if not pairs:
        return _unavailable(key, label, "還沒在 Meta 找到這期的廣告組合。")

    campaign_budgets: dict = {}
    if any("daily_budget" not in adset for _, adset in pairs):
        # 廣告組沒有自己的日預算＝活動層 CBO 扛預算（票面規則），才多打這一次；
        # 每組都有自己日預算的帳戶（ABO）完全不用叫這支，省一次 API。
        campaigns, err = _fetch_entities(account_id, "campaign", _CAMPAIGN_FIELDS)
        if err is not None:
            return _unavailable(key, label, f"讀不到 Meta 的行銷活動預算：{err}")
        campaign_budgets = {c["id"]: c.get("daily_budget") for c in campaigns if c.get("id")}

    offenders = []
    for pkg, adset in pairs:
        meta_raw = adset["daily_budget"] if "daily_budget" in adset else campaign_budgets.get(adset.get("campaign_id"))
        meta_budget = _parse_budget(meta_raw)
        baseline = round(pkg.get("daily_budget") or 0)
        if meta_budget is None or meta_budget != baseline:
            name = pkg.get("adset_name") or adset.get("name") or ""
            shown = f"{meta_budget:,}" if meta_budget is not None else "讀不到"
            offenders.append(f"「{name}」後台設 {shown}，底案是 {baseline:,}")
    if not offenders:
        return _available(key, label, True, "每組廣告的日預算都跟底案一致。")
    extra = f"（還有 {len(offenders) - 1} 組也對不上）" if len(offenders) > 1 else ""
    return _available(key, label, False, f"{offenders[0]}。{extra}")


def _landing_page_check(packages: list) -> dict:
    key, label = "qa_landing_page_click_test", "到達頁已實點測試"
    if not packages:
        return _unavailable(key, label, "這期還沒有交接包，先產出交接包才能探測到達網址。")
    all_ok = all(_probe_url(p.get("full_url") or "") for p in packages)
    note = ("全部到達網址都能正常打開。" if all_ok else
           "至少一組到達網址打不開或逾時，系統只確認網址打得開，內容正不正確還是要自己看一眼。")
    return _available(key, label, all_ok, note)


def _probe(conn, brand_id: str, cycle_id: str) -> list:
    account_id = meta_mcp.raw_account_id()
    packages = ads_handoff.list_packages(conn, brand_id, cycle_id)
    datasets, datasets_err = _fetch_datasets(account_id)
    pairs, match_err = _match_adsets(conn, brand_id, cycle_id, packages, account_id)
    return [
        _pixel_check(conn, brand_id, datasets, datasets_err),
        _audience_exclusion_check(pairs, match_err),
        _emq_check(datasets, datasets_err),
        _budget_check(pairs, match_err, account_id),
        _landing_page_check(packages),
    ]


def results(conn, brand_id: str, cycle_id: str) -> list:
    """上線授權頁 QA 五項提醒的系統覆核結果（`AutoCheckResult[]`，形狀不變）。
    決策 1：`passed=True` 時前端不畫勾選框，改顯示「系統已驗過」；`checked` 因此只在
    `available=False` 或覆核沒過時才有意義，但這裡不論如何都照舊回傳，維持既有欄位。"""
    cache_key = (brand_id, cycle_id)
    now = time.monotonic()
    cached = _cache.get(cache_key)
    if cached and cached[0] > now:
        base = cached[1]
    else:
        base = _probe(conn, brand_id, cycle_id)
        _cache[cache_key] = (now + _CACHE_TTL_SECONDS, base)

    qa_checked = {i["key"]: i["checked"] for i in ads_checklist.qa_launch_status(conn, brand_id)}
    return [{**item, "checked": qa_checked.get(item["key"], False)} for item in base]


def demo() -> None:
    """python -m app.ads.qa_autocheck —— 純函數自檢：預算字串解析、資料集去重取最新。"""
    assert _parse_budget("NT$2,143 TWD") == 2143
    assert _parse_budget(None) is None
    assert _parse_budget("") is None

    datasets = [
        {"dataset_id": "px1", "is_active": True, "last_fired_time": "1969-12-31T16:00:00-0800"},
        {"dataset_id": "px1", "is_active": True, "last_fired_time": "2026-08-22T09:00:00+0800"},
    ]
    best = _dedupe_datasets(datasets)
    assert best["px1"]["last_fired_time"] == "2026-08-22T09:00:00+0800"
    print("qa_autocheck 自檢通過")


if __name__ == "__main__":
    demo()
