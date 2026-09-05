"""app/tools/simulate_meta_spend.py — 票 01（T6c）：把這個 session 驗證用的暫存腳本收進
repo，讓成效判讀（與日後任何人）不必等真廣告花到錢才能開發。

假的**只有最外層那道網路呼叫**（`app.meta.graph.fetch_page`）：底下解析／寫庫
（`app.meta.daily_pull.run_daily_pull`）、綁定（`app.schedule.binding.bind_tree`，真名稱
比對）、座標落地（`app.schedule.repository.persist_creative_result`）跑的都是真程式，不是
這支工具自己重寫的簡化版。假回應的形狀照 `app.meta.graph` 的欄位清單，稀疏度／覆蓋率照
`.scratch/adloop/GRILL.md` 對真帳號量到的比例：81% 的「廣告×日」沒有列、約六成的列帶
roas（`omni_purchase`），roas 落在 0.42–5。

活動樹只放 3 個最深層節點（廣告01／02／03），第 4 則廣告（廣告04）只存在於平台端，故意不
進樹——`bind_tree()` 只比對樹上有的名字，廣告04 因此永遠綁不上，它的花費落進
`performance.py` 的「未標座標」桶子（那是桶子不是破洞，ADR 0057 §5）。

CLI：`uv run python -m app.tools.simulate_meta_spend --org org_bughunt --brand brd_bughunt`。
只准在 `BRAND_OS_ENV != production` 時執行（ADR 0062 既有環境宣告）——見 `__main__` 區塊。
"""

import argparse
import json
import random
from datetime import date, timedelta

from app.core.db import connection, jsonb, new_id
from app.meta import daily_pull, graph
from app.meta import repository as meta_repo
from app.schedule import binding as binding_mod
from app.schedule import repository as schedule_repo

random.seed(20260906)

ACCOUNT_ID = "368741390835357"
CURRENCY = "TWD"
TIMEZONE = "Asia/Taipei"

CAMPAIGN = ("120251600000000001", "Beast Gummy｜廣泛開發｜銷售")
ADSETS = [
    ("120251610000000001", "Beast Gummy｜廣泛開發｜廣泛", CAMPAIGN[0]),
    ("120251610000000002", "Beast Gummy｜廣泛開發｜興趣", CAMPAIGN[0]),
]
# (ad_id, ad_name, adset_id, 每日花費區間, roas 區間)——廣告04 刻意不進活動樹（見檔頭）。
ADS = [
    ("120251641305860671", "Beast Gummy｜廣泛開發｜廣泛｜廣告01", ADSETS[0][0],
     (180, 320), (2.2, 5.0)),
    ("120251641305860672", "Beast Gummy｜廣泛開發｜廣泛｜廣告02", ADSETS[0][0],
     (150, 260), (0.42, 1.1)),
    ("120251641305860673", "Beast Gummy｜廣泛開發｜興趣｜廣告03", ADSETS[1][0],
     (90, 200), (1.4, 3.1)),
    ("120251641305860674", "Beast Gummy｜廣泛開發｜興趣｜廣告04", ADSETS[1][0],
     (60, 140), (0.8, 1.6)),
]

# 七維座標，只標前三則廣告（key 是活動樹的 node_key，深度 3："<行銷活動>.<廣告組合>.<廣告>"）。
COORDINATES = {
    "1.1.1": {"audience": "陌生・知道問題", "pain": "怕買錯", "angle": "稀缺性行銷",
              "hook": "痛點提問", "proof": "顧客評論原話", "offer": "折扣特價", "format": "單圖"},
    "1.1.2": {"audience": "互動過・沒買", "pain": "太貴", "angle": "產品講解",
              "hook": "結果導向", "proof": "無證明", "offer": "免運", "format": "影片"},
    "1.2.1": {"audience": "陌生・知道問題", "pain": "太貴", "angle": "功能收益講解",
              "hook": "反差對比", "proof": "銷售數據", "offer": "無優惠", "format": "輪播"},
}


# ---------------------------------------------------------------------------
# 假 Graph 回應：insights（三層花費）＋物件清單（campaigns/adsets/ads，`bind_tree()` 真名稱
# 比對要用）。形狀照 `app/meta/graph.py` 的欄位清單，不是這支工具自己發明的。
# ---------------------------------------------------------------------------

def _actions(clicks: int, purchases: int) -> list:
    out = [
        {"action_type": "link_click", "value": str(clicks)},
        {"action_type": "landing_page_view", "value": str(max(0, clicks - clicks // 4))},
        {"action_type": "post_engagement", "value": str(clicks * 3)},
        {"action_type": "page_engagement", "value": str(clicks * 3)},
        {"action_type": "view_content", "value": str(clicks * 2)},
    ]
    if purchases:
        out += [{"action_type": "omni_purchase", "value": str(purchases)},
                {"action_type": "purchase", "value": str(purchases)},
                {"action_type": "offsite_conversion.fb_pixel_purchase", "value": str(purchases)}]
    return out


def _ad_rows(days: list) -> list:
    rows = []
    for ad_id, ad_name, adset_id, (lo, hi), (rlo, rhi) in ADS:
        for day in days:
            if random.random() < 0.25:  # 稀疏：81%「廣告×日」沒有列（GRILL.md §1(d)）——這裡
                continue                 # 用 25% 每則廣告的機率大致對得上整體量到的比例。
            spend = round(random.uniform(lo, hi), 2)
            impressions = int(spend * random.uniform(28, 55))
            clicks = int(impressions * random.uniform(0.008, 0.028))
            tracked = random.random() < 0.6  # 約六成的列帶 roas
            roas = round(random.uniform(rlo, rhi), 6) if tracked else None
            purchases = max(1, int(clicks * 0.05)) if tracked else 0
            row = {
                "campaign_id": CAMPAIGN[0], "adset_id": adset_id, "ad_id": ad_id,
                "ad_name": ad_name, "spend": f"{spend:.2f}", "impressions": str(impressions),
                "clicks": str(clicks), "actions": _actions(clicks, purchases),
                "date_start": day.isoformat(), "date_stop": day.isoformat(),
            }
            if roas is not None:
                row["purchase_roas"] = [{"action_type": "omni_purchase", "value": f"{roas}"}]
                row["action_values"] = [{"action_type": "omni_purchase",
                                          "value": f"{round(spend * roas, 2)}"}]
            rows.append(row)
    return rows


def _rollup(ad_rows: list, level: str) -> list:
    """campaign/adset 是同一批 ad 列往上捲——跟 Meta 自己按層級回應的形狀一樣，三層才會
    總額相等（done-check 5）。"""
    buckets: dict = {}
    for r in ad_rows:
        if level == "campaign":
            key = (r["campaign_id"], r["date_start"])
            ident = {"campaign_id": r["campaign_id"], "campaign_name": CAMPAIGN[1]}
        else:
            key = (r["adset_id"], r["date_start"])
            name = next(a[1] for a in ADSETS if a[0] == r["adset_id"])
            ident = {"campaign_id": r["campaign_id"], "adset_id": r["adset_id"],
                     "adset_name": name}
        b = buckets.setdefault(key, {"ident": ident, "date": r["date_start"], "spend": 0.0,
                                      "impressions": 0, "clicks": 0, "rev": 0.0,
                                      "spend_tracked": 0.0})
        b["spend"] += float(r["spend"])
        b["impressions"] += int(r["impressions"])
        b["clicks"] += int(r["clicks"])
        if "purchase_roas" in r:
            b["spend_tracked"] += float(r["spend"])
            b["rev"] += float(r["action_values"][0]["value"])
    out = []
    for b in buckets.values():
        row = {**b["ident"], "spend": f"{b['spend']:.2f}", "impressions": str(b["impressions"]),
               "clicks": str(b["clicks"]), "date_start": b["date"], "date_stop": b["date"],
               "actions": _actions(b["clicks"], 1)}
        if b["spend_tracked"]:
            row["purchase_roas"] = [{"action_type": "omni_purchase",
                                      "value": f"{b['rev'] / b['spend_tracked']:.6f}"}]
            row["action_values"] = [{"action_type": "omni_purchase", "value": f"{b['rev']:.2f}"}]
        out.append(row)
    return out


_INSIGHTS_CACHE: dict = {}


def _insights_response(level: str, since: date, until: date) -> dict:
    """三層必須互相對得上，所以同一段日期的 ad 列只算一次、快取起來，campaign／adset 是
    對同一批列往上捲（見 `_rollup`）。"""
    days = [since + timedelta(days=i) for i in range((until - since).days + 1)]
    if (since, until) not in _INSIGHTS_CACHE:
        _INSIGHTS_CACHE[(since, until)] = _ad_rows(days)
    ad_rows = _INSIGHTS_CACHE[(since, until)]
    data = ad_rows if level == "ad" else _rollup(ad_rows, level)
    return {"data": data, "paging": {"cursors": {"before": "MAZ", "after": "NjQZD"}}}


def _fake_fetch_page(url: str, *, params: dict, headers: dict) -> dict:
    """`graph.fetch_page` 的替身：insights（`time_range` 參數）與 `bind_tree()` 要用的三個
    物件清單端點（/campaigns、/adsets、/ads）都在這裡分派——跟 `graph.list_campaigns`／
    `list_ad_sets`／`list_ads` 打的是同一組 URL 形狀，只是不連真的網路。"""
    if url.endswith("/campaigns"):
        return {"data": [{"id": CAMPAIGN[0], "name": CAMPAIGN[1], "effective_status": "ACTIVE"}]}
    if url.endswith("/adsets"):
        return {"data": [{"id": a[0], "name": a[1], "effective_status": "ACTIVE"} for a in ADSETS]}
    if url.endswith("/ads"):
        adset_id = url.rsplit("/", 2)[-2]
        return {"data": [{"id": a[0], "name": a[1], "effective_status": "ACTIVE"}
                         for a in ADS if a[2] == adset_id]}
    time_range = json.loads(params["time_range"])
    return _insights_response(
        params["level"], date.fromisoformat(time_range["since"]),
        date.fromisoformat(time_range["until"]),
    )


# ---------------------------------------------------------------------------
# 灌資料本體：帳號綁定 → 三層花費 → 建樹 → 綁三個深度 3 節點（真名稱比對）→ 標七維座標。
# ---------------------------------------------------------------------------

def _tree_payload() -> dict:
    def leaf(name: str) -> dict:
        return {"name": name, "fields": [], "share": None, "warnings": [], "children": []}

    nodes = [{
        "name": CAMPAIGN[1], "fields": [], "share": None, "warnings": [],
        "children": [
            {"name": ADSETS[0][1], "fields": [], "share": 0.6, "warnings": [],
             "children": [leaf(ADS[0][1]), leaf(ADS[1][1])]},
            {"name": ADSETS[1][1], "fields": [], "share": 0.4, "warnings": [],
             "children": [leaf(ADS[2][1])]},  # 廣告04 故意不放進樹——見檔頭
        ],
    }]
    return {"levels": ["行銷活動", "廣告組合", "廣告"], "budget_level": 2, "nodes": nodes}


def _insert_tree_row(conn, org_id: str, brand_id: str, daily_budget: float) -> str:
    tree_id = new_id("llm")
    rendered = "活動樹。\n\n```json\n" + json.dumps(_tree_payload(), ensure_ascii=False) + "\n```"
    conn.execute(
        "INSERT INTO llm_task (id, org_id, brand_id, task_type, context_scope_json,"
        " input_context_ids_json, input_context_hash, knowledge_item_ids_json, brand_version,"
        " prompt_template_id, prompt_template_version, provider, model, status, attempt_no,"
        " started_at, rendered_output, finished_at)"
        " VALUES (%s,%s,%s,'schedule_tree',%s,'[]','','[]',1,'simulate_meta_spend','v1',"
        " 'simulated','simulated','succeeded',1,now(),%s,now())",
        (tree_id, org_id, brand_id,
         jsonb({"daily_budget": daily_budget, "plan_index": 0}), rendered),
    )
    conn.commit()
    return tree_id


def run(org_id: str, brand_id: str) -> None:
    graph.fetch_page = _fake_fetch_page  # 只換最外層的網路呼叫（見檔頭）

    with connection() as conn:
        # 1. 帳號綁定
        meta_repo.save_token(conn, org_id, "SIMULATED-TOKEN")
        meta_repo.upsert_accounts(conn, org_id, [{
            "account_id": ACCOUNT_ID, "name": "BP AD", "currency": CURRENCY,
            "timezone_name": TIMEZONE,
        }])
        conn.commit()
        local_id = next(
            a["id"] for a in meta_repo.list_accounts(conn, org_id) if a["account_id"] == ACCOUNT_ID
        )
        meta_repo.bind(conn, org_id, brand_id, local_id)
        conn.commit()

        # 3. 建樹（在灌花費之前插入，讓 bind_tree 有名字可以比對）
        tree_id = _insert_tree_row(conn, org_id, brand_id, daily_budget=1500.0)

    # 2. 三層花費——走真的 `run_daily_pull()`（今天往回 7 天，見該檔檔頭），不是這支工具
    #    自己重寫一份 upsert。
    daily_pull.run_daily_pull(org_id)

    with connection() as conn:
        # 4. 綁三個深度 3 節點：真名稱比對，比照 `_run_bind` 路由呼叫的同一支函式。
        tree_row = conn.execute(
            "SELECT * FROM llm_task WHERE id = %s", (tree_id,)
        ).fetchone()
        assert tree_row is not None  # 剛插入的那一列，找不到代表資料庫壞了
        failures = binding_mod.bind_tree(conn, dict(tree_row), org_id, brand_id)
        if failures:
            raise RuntimeError(f"模擬資料綁定失敗（不應該發生）：{failures}")

        # 5. 標七維座標——只標前三則廣告，第四則故意不出現在這裡（未標座標桶子要一直有東西）。
        ads = [
            {"node_key": node_key, "coordinates": coords, "visual_tone": None,
             "visual_concept": None,
             "fields": [{"label": "文案", "value": [f"模擬素材 {node_key}"]}]}
            for node_key, coords in COORDINATES.items()
        ]
        schedule_repo.persist_creative_result(
            conn, org_id, brand_id, task_id=new_id("llm"), source_tree_task_id=tree_id, ads=ads,
        )
        conn.commit()

    print(f"模擬資料完成：org={org_id} brand={brand_id} tree_task_id={tree_id}")


if __name__ == "__main__":
    # `import app.main` 觸發 `.env` 載入＋完整組裝（比照 `app/meta/daily_pull.py` 既有慣例）
    # ——BRAND_OS_ENV 要讀得到 `.env` 裡的值，非先做這一步不可；做完立刻檢查環境，
    # 是這支工具除了 argparse 之外唯一會先做的事，其餘一律在確認過環境之後才動。
    import app.main  # noqa: F401 — 觸發完整組裝與 .env 載入，不需要 app 物件本身
    from app.core.config import settings

    if settings().brand_os_env == "production":
        raise SystemExit(
            "app.tools.simulate_meta_spend 只能在 BRAND_OS_ENV != production 時執行——"
            "這支工具會直接灌假的 Meta 花費／綁定／座標資料，正式環境絕對不能跑到。"
        )

    _parser = argparse.ArgumentParser(
        prog="python -m app.tools.simulate_meta_spend",
        description="灌模擬 Meta 花費資料：帳號綁定、三層花費、活動樹、深度 3 綁定、七維座標。",
    )
    _parser.add_argument("--org", required=True, help="組織 id，例如 org_bughunt")
    _parser.add_argument("--brand", required=True, help="品牌 id，例如 brd_bughunt")
    _args = _parser.parse_args()

    run(_args.org, _args.brand)
