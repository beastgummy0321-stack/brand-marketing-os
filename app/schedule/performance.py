"""app/schedule/performance.py — 票 T5（ADR 0057）：花費透過深度 3 綁定接上七維座標。

Private to app/schedule/（集裝箱憲章第一節）：只有 `routes.py` 呼叫這裡的
`brand_creative_performance()`；`jobs.py`（票 01，同一個套件內）呼叫 `ad_performance()`——
兩支呼叫端都在 `app/schedule/` 套件內部，外面任何模組都不 import 這個檔案。

join 的路徑（ADR 0057 §1），完全比照 `period.compute_money()` 既有的形狀——不是一支跨模組
的 SQL：`meta_repo.daily_entity_spend(level="ad")` 讀花費原始數字，`schedule_repo` 的兩支
新讀取（`depth_three_bindings`／`creative_candidates_for_brand`）讀這個模組自己的綁定與
候選，兩邊在 Python 這裡接起來。`meta_entity_spend` 屬於 `app/meta`；`creative_candidate`／
`channel_entity_map` 屬於 `app/schedule`——跨模組 SQL join 會把 `app/schedule` 建進另一個
模組的表裡（集裝箱憲章第一節）。

哪一支綁定算數（票 10，ADR 0064 §1）：`channel_entity_map` 深度 3、`source_tree_task_id`
不是 NULL 的每一列——一列自己就名著它是哪一棵樹綁的，且那一棵樹永遠不會被別的樹改寫，
所以不必再問「還跟現在最新那棵樹的名字對得上嗎」（那張否決票只守著畫面的
`binding.tree_with_bindings()`，這裡不重用）。一個平台實體可能被兩棵樹各綁過一次，這裡
按 ADR 0064 §2 用花費那一天配對「那天已經生效的最新一次綁定」。哪一份候選算數：那個
位置 `(node_key, source_tree_task_id)` 最新一輪的 `creative_candidate`（ADR 0057 §2：
绝不是「最新的樹」）。

`未標座標`永遠是桶子，不是破洞（ADR 0057 §5）：一支花費列碰不到任何一個維度的座標，就落
進那個維度自己的 `untagged`；碰不到任何一個維度（沒綁定、綁定沒過否決票、候選還沒有任何
座標）就再落進整個幣別的 `untagged`。第 5 節的矛盾檢查已經裁決：`untagged` 是**逐維度**
一份，不是整個幣別一份——`values[]`＋`untagged` 在每一個維度自己內部都要加總等於
`total_spend`，這是這張票存在的理由（done-check 1）。

`revenue`／`roas`／`roas_coverage`（ADR 0057 §7）：只在 Python 這裡算，絕不重用
`meta_repo.spend_summary()` 的 `bool_and(roas IS NOT NULL)`——那條規則是「範圍內任何一天
沒追蹤，整組回 None」，套在一整個月的座標上會把 14 天有追蹤的營收也一起吃掉。這裡反過來：
`revenue` 只加總「有追蹤到 roas」的那些列，`roas_coverage` 誠實地回「幾列裡有幾列有追蹤」。
"""

from datetime import date, datetime, timedelta

from app.brand_intelligence import repository as bi_repo
from app.core import settings as coresettings
from app.meta import repository as meta_repo
from app.schedule import binding as binding_mod
from app.schedule import repository as schedule_repo
from app.schedule import state
from app.schedule.creative import COORDINATE_KEYS


def _vetted_depth_three_bindings(conn, org_id: str, brand_id: str) -> dict:
    """票 10（ADR 0064 §1）：`(node_key, source_tree_task_id) → {"external_id",
    "created_at"}` for every mapped depth-3 binding whose `source_tree_task_id` is not NULL
    (rows bound before that column existed have no tree to find a candidate against — they
    fall into `untagged`, not a special case).

    不再讀 `state._display_task_row()` 也不再重用 `binding.tree_with_bindings()` 的名字
    否決票：一列現在自己就名著它是哪一棵樹綁的，而那一棵樹永遠不會被別的樹改寫
    （`upsert_binding()` 的唯一鍵已經把 `source_tree_task_id` 算進去），所以「還跟現在
    最新的那棵樹的名字對得上嗎」這張否決票已經沒有東西可以否決——它以前正是把上一期
    的綁定打成 `untagged` 的那一半成因（ADR 0064「問題」段）。那張否決票依然守著畫面
    （`binding.tree_with_bindings()` 本身沒有改）。"""
    return {
        slot: {"external_id": row["external_id"], "created_at": row["created_at"]}
        for slot, row in schedule_repo.depth_three_bindings(
            conn, org_id, brand_id, binding_mod.CHANNEL_KEY,
        ).items()
        if slot[1] is not None
    }


def _binding_date(conn, org_id: str, created_at) -> date:
    """一列綁定的 `created_at` 是 timestamptz（psycopg 回傳 UTC 時刻）；花費的 `spend_date`
    是組織時區的日曆日——兩邊要先落在同一個時區才能比較，否則台北在 UTC 還沒跨到下一天
    的那 8 小時裡，今天綁的東西會被判成「明天才生效」（同 `tree_approval._approval_
    overspend()` 對 `approved_at` 的既有處理）。"""
    if isinstance(created_at, datetime):
        return created_at.astimezone(coresettings.org_timezone(conn, org_id=org_id)).date()
    return created_at


def _bindings_by_entity(conn, org_id: str, vetted: dict) -> dict:
    """`external_id → [(binding_date, slot), ...]`，依 `binding_date`（組織時區的日曆日）
    由舊到新排序——同一個平台實體可能被兩棵樹各綁過一次（ADR 0064 §2：期與期之間重複
    使用同一支活動／組合／廣告），呼叫端按花費那一天落在哪一次綁定之後決定歸屬。"""
    by_entity: dict = {}
    for slot, row in vetted.items():
        binding_date = _binding_date(conn, org_id, row["created_at"])
        by_entity.setdefault(row["external_id"], []).append((binding_date, slot))
    for bindings in by_entity.values():
        bindings.sort(key=lambda item: item[0])
    return by_entity


def _slot_for_spend(bindings: list, spend_date) -> tuple | None:
    """ADR 0064 §2：花費那一天屬於「`created_at` 那一天 <= 花費那一天」裡最新的一次綁定；
    比所有綁定都早的花費歸最早的那一次。`bindings` 已經照 `created_at` 由舊到新排序，所以
    由頭到尾走一遍、留下最後一個符合的就是答案；一個都不符合就是最早那一個。"""
    if not bindings:
        return None
    chosen = bindings[0][1]
    for binding_date, slot in bindings:
        if binding_date <= spend_date:
            chosen = slot
    return chosen


def _coordinate_labels(conn, org_id: str, brand_id: str) -> dict:
    """`(dimension, key) → label`，供把候選存的 key 轉成使用者看得懂的中文名稱。讀
    `list_coordinates()`（跟品牌智庫「創意座標」分頁同一支既有讀取，不另開一條）。"""
    return {
        (c["dimension"], c["key"]): c["label"]
        for c in schedule_repo.list_coordinates(conn, org_id, brand_id)
    }


def _bucket(rows: list) -> dict:
    """一組花費列（一個座標值，或 `未標座標`）→ 畫面要的七個聚合數字，外加 `ad_count`。
    `revenue`／`roas` 只用有追蹤到 `roas` 的那些列（ADR 0057 §7），`roas_coverage` 用**這
    整組**列數當分母——一列是一個實體一天，不是一個廣告。

    票 01（T6c 決定 11，`docs/contracts/schedule.md`「One coordinate has two ROAS values」）：
    `roas`（既有欄位，更名意義不變）是**樂觀值**——分母只算有追蹤到的花費；`roas_conservative`
    是**保守值**——同一份 `revenue`，分母換成這組**全部**花費（含沒追蹤到的）。兩個值都是真
    的，畫哪一個都是在說謊的另一半，所以兩個都給，不畫單一數字。不重寫 `quadrant.ts` 那份
    算術——這裡只是多除一次，前端仍是唯一畫圖的地方。"""
    spend = sum(r["spend"] for r in rows)
    with_roas = [r for r in rows if r["roas"] is not None]
    revenue: float | None = None
    roas: float | None = None
    roas_conservative: float | None = None
    if with_roas:
        spend_with_roas = sum(r["spend"] for r in with_roas)
        revenue = sum(r["spend"] * r["roas"] for r in with_roas)
        roas = (revenue / spend_with_roas) if spend_with_roas else None
        roas_conservative = (revenue / spend) if spend else None
    return {
        "spend": round(spend, 2),
        "impressions": sum(r["impressions"] for r in rows),
        "clicks": sum(r["clicks"] for r in rows),
        "revenue": round(revenue, 2) if revenue is not None else None,
        # roas／roas_conservative／roas_coverage 是比率，不是錢——比照 spend_summary 既有
        # 慣例（ctr／cpc／cpm 也不在 Python 端 round()），原始精度直接穿出去，畫面自己決定
        # 顯示幾位。
        "roas": roas,
        "roas_conservative": roas_conservative,
        "roas_coverage": (len(with_roas) / len(rows)) if rows else 0.0,
        "ad_count": len({r["entity_id"] for r in rows}),
    }


def _untagged_bucket(rows: list) -> dict:
    """`未標座標`桶子只有 `spend`／`ad_count` 兩欄（ticket 字面例子），不是 `_bucket()`
    的六欄——它不代表任何一個座標，印曝光／點擊／營收／ROAS 沒有意義。"""
    return {
        "spend": round(sum(r["spend"] for r in rows), 2),
        "ad_count": len({r["entity_id"] for r in rows}),
    }


def _reaches_any(candidate: dict | None) -> bool:
    return bool(candidate and any(candidate.get(f"{d}_key") for d in COORDINATE_KEYS))


def _currency_view(currency: str, rows: list, row_candidate: dict, labels: dict) -> dict:
    """票 10（ADR 0064 §2）：`row_candidate` 現在是 `(entity_id, spend_date) → candidate`
    ——同一個 `entity_id` 在不同的日子可能落在不同一次綁定（因此不同一份候選），不再是
    `entity_id → candidate` 那種整個月只有一份答案的形狀。"""
    total_spend = round(sum(r["spend"] for r in rows), 2)
    currency_untagged_rows = [
        r for r in rows
        if not _reaches_any(row_candidate.get((r["entity_id"], r["spend_date"])))
    ]

    dimensions = []
    for dimension in COORDINATE_KEYS:
        column = f"{dimension}_key"
        buckets: dict = {}
        for row in rows:
            candidate = row_candidate.get((row["entity_id"], row["spend_date"]))
            key = candidate.get(column) if candidate else None
            buckets.setdefault(key, []).append(row)
        dim_untagged_rows = buckets.pop(None, [])
        values = [
            {"key": key, "label": labels.get((dimension, key), key), **_bucket(value_rows)}
            for key, value_rows in buckets.items()
        ]
        dimensions.append({
            "dimension": dimension,
            "untagged": _untagged_bucket(dim_untagged_rows),
            "values": values,
        })

    return {
        "currency": currency,
        "total_spend": total_spend,
        "untagged": _untagged_bucket(currency_untagged_rows),
        "dimensions": dimensions,
    }


def brand_creative_performance(conn, org_id: str, brand_id: str) -> dict:
    """`GET /api/schedule/brands/{brand_id}/creative-performance` 的本體——本月（組織自己
    時區的日曆月，跟 `app/meta/routes.py::brand_spend` 同一個窗口）逐座標值的花費／曝光／
    點擊／營收／ROAS／資料覆蓋率／廣告數，`未標座標`是每個維度自己的桶子（ticket 矛盾
    檢查段的裁決）。`currencies` 是清單，絕不跨幣別相加（ADR 0057 §4）。"""
    month_start, month_end = state._current_month_window(conn, org_id)
    account_ids = meta_repo.bound_account_ids_for_brand(conn, org_id, brand_id)
    daily_rows = meta_repo.daily_entity_spend(
        conn, org_id, account_ids, month_start, month_end, level="ad",
    )

    vetted = _vetted_depth_three_bindings(conn, org_id, brand_id)
    bindings_by_entity = _bindings_by_entity(conn, org_id, vetted)
    candidates = schedule_repo.creative_candidates_for_brand(conn, org_id, brand_id)
    labels = _coordinate_labels(conn, org_id, brand_id)

    # 票 10（ADR 0064 §2）：一個 `entity_id` 可能落在兩次綁定之間，所以候選要按
    # `(entity_id, spend_date)` 逐列查，不是整個月只查一次——同一個 `entity_id` 在不同的
    # 花費日可能屬於不同一次綁定（因此不同一個座標）。`row_candidate` 每個
    # `(entity_id, spend_date)` 只算一次，rows 裡同一組合最多重複出現在同一個幣別的清單
    # 裡一次（`daily_entity_spend()` 的 `GROUP BY (spend_date, entity_id, currency)`）。
    row_candidate = {
        (row["entity_id"], row["spend_date"]): candidates.get(
            _slot_for_spend(bindings_by_entity.get(row["entity_id"], []), row["spend_date"])
        )
        for row in daily_rows
    }

    rows_by_currency: dict = {}
    for row in daily_rows:
        rows_by_currency.setdefault(row["currency"], []).append(row)

    currencies = [
        _currency_view(currency, rows, row_candidate, labels)
        for currency, rows in sorted(rows_by_currency.items())
    ]

    return {
        "window": {
            "start_date": month_start.isoformat(),
            "end_date": (month_end - timedelta(days=1)).isoformat(),
        },
        "currencies": currencies,
    }


def ad_performance(conn, org_id: str, brand_id: str) -> dict:
    """票 01（`docs/issues/plan-quality/`）：這個帳戶本月逐廣告的花費／ROAS，供
    `jobs._account_performance_text()` 組進出方案的 prompt——跟 `brand_creative_performance()`
    同一個窗口（`state._current_month_window`），但不接座標，直接照 `spend`
    由大到小逐廣告列出，讓 prompt 能指名「哪一則廣告」。

    `conversion_goal` 讀 `brand.conversion_goal`（哪個 action_type 算轉換是使用者在設定頁
    填的，這裡只是原樣讀出來傳給 `spend_summary()`，不重新判斷——集裝箱憲章：不碰別人的表，
    這裡是透過 `app.brand_intelligence.repository` 這支既有讀取碰，不是直接查 `brand` 表）。

    `total`／每一則廣告都用既有的 `_bucket()`（保守／樂觀 ROAS 兩個值都給，ADR 0057 §7）；
    `entity_name`／`cpa` 來自 `spend_summary()`（同一批 `daily_entity_spend()` 列聚合出的
    另一份既有讀取，不是另開一支查詢）。**一個幣別一個區塊，絕不跨幣別相加**（ADR 0057
    §4，同 `brand_creative_performance()`）。沒有綁定帳號或這個月沒有任何花費列 →
    `currencies` 是空陣列，`conversion_goal` 依然照填（畫面／prompt 兩邊都要知道「有沒有
    設定轉換目標」跟「有沒有資料」是兩件事）。"""
    month_start, month_end = state._current_month_window(conn, org_id)
    window = {
        "start_date": month_start.isoformat(),
        "end_date": (month_end - timedelta(days=1)).isoformat(),
    }
    conversion_goal = (bi_repo.get_brand(conn, brand_id) or {}).get("conversion_goal")

    account_ids = meta_repo.bound_account_ids_for_brand(conn, org_id, brand_id)
    daily_rows = meta_repo.daily_entity_spend(
        conn, org_id, account_ids, month_start, month_end, level="ad",
    )
    if not daily_rows:
        return {"window": window, "conversion_goal": conversion_goal, "currencies": []}

    summary = meta_repo.spend_summary(
        conn, org_id, account_ids, month_start, month_end, level="ad",
        conversion_goal=conversion_goal,
    )
    name_and_cpa = {e["entity_id"]: (e["entity_name"], e["cpa"]) for e in summary["entities"]}

    rows_by_currency: dict = {}
    for row in daily_rows:
        rows_by_currency.setdefault(row["currency"], []).append(row)

    currencies = []
    for currency, rows in sorted(rows_by_currency.items()):
        rows_by_ad: dict = {}
        for row in rows:
            rows_by_ad.setdefault(row["entity_id"], []).append(row)
        ads = [
            {
                "entity_id": entity_id,
                "entity_name": name_and_cpa.get(entity_id, (entity_id, None))[0],
                "cpa": name_and_cpa.get(entity_id, (entity_id, None))[1],
                **_bucket(ad_rows),
            }
            for entity_id, ad_rows in rows_by_ad.items()
        ]
        ads.sort(key=lambda a: -a["spend"])
        currencies.append({"currency": currency, "total": _bucket(rows), "ads": ads})

    return {"window": window, "conversion_goal": conversion_goal, "currencies": currencies}
