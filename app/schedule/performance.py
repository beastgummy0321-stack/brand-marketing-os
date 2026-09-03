"""app/schedule/performance.py — 票 T5（ADR 0057）：花費透過深度 3 綁定接上七維座標。

Private to app/schedule/（集裝箱憲章第一節）：只有 `routes.py` 呼叫這裡的
`brand_creative_performance()`，外面任何模組都不 import 這個檔案。

join 的路徑（ADR 0057 §1），完全比照 `period.compute_money()` 既有的形狀——不是一支跨模組
的 SQL：`meta_repo.daily_entity_spend(level="ad")` 讀花費原始數字，`schedule_repo` 的兩支
新讀取（`depth_three_bindings`／`creative_candidates_for_brand`）讀這個模組自己的綁定與
候選，兩邊在 Python 這裡接起來。`meta_entity_spend` 屬於 `app/meta`；`creative_candidate`／
`channel_entity_map` 屬於 `app/schedule`——跨模組 SQL join 會把 `app/schedule` 建進另一個
模組的表裡（集裝箱憲章第一節）。

哪一支綁定算數：`channel_entity_map` 深度 3 的列，且 `node_name_at_bind` 仍然跟目前那棵樹
同一個 `node_key` 的名字相符（ADR 0055 §4 的讀時否決票，跟 `binding.tree_with_bindings()`
套用在每一層的規則完全一樣——這裡重用那支函式本身，不是另外重寫一份否決邏輯）。哪一份
候選算數：那個位置 `(node_key, source_tree_task_id)` 最新一輪的 `creative_candidate`
（ADR 0057 §2：绝不是「最新的樹」）。

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

from datetime import timedelta

from app.meta import repository as meta_repo
from app.schedule import binding as binding_mod
from app.schedule import repository as schedule_repo
from app.schedule import state
from app.schedule.creative import COORDINATE_KEYS


def _leaf_bound_ids(nodes: list) -> dict:
    """活動樹最深層（沒有 `children` 的）節點裡，已經通過名字否決票、真的綁定的
    `node_key → bound_external_id`——`state._leaf_ad_nodes()` 也走同一個遞迴形狀，但那支
    給創意產生流程用，特意不帶 `bound_external_id`（呼叫端只比對名字）；這裡要的正是
    那一欄，所以另外寫這支小一號的，不去動 `state.py` 那支既有函式的回傳形狀。"""
    result: dict = {}
    for node in nodes:
        if node["children"]:
            result.update(_leaf_bound_ids(node["children"]))
        elif node["bound_external_id"] is not None:
            result[node["node_key"]] = node["bound_external_id"]
    return result


def _vetted_depth_three_bindings(conn, org_id: str, brand_id: str) -> dict:
    """`node_key → {"external_id", "source_tree_task_id"}`，只留下：(1) 深度 3、
    `local_state='mapped'` 的綁定，(2) `node_name_at_bind` 還跟目前那棵樹同一個 `node_key`
    的名字相符（`binding.tree_with_bindings()` 對每一層都套用的同一條讀時否決票，這裡
    重用它，不重寫），(3) `source_tree_task_id` 不是 NULL（ADR 0057 §2：這一票之前綁的
    列沒有這一欄，找不到候選，落進 `untagged`，不是特例）。"""
    raw = schedule_repo.depth_three_bindings(conn, org_id, brand_id, binding_mod.CHANNEL_KEY)
    if not raw:
        return {}
    tree_row, _running = state._display_task_row(conn, brand_id, state.TREE_TASK_TYPE)
    if tree_row is None:
        return {}
    tree = binding_mod.tree_with_bindings(conn, tree_row, org_id, brand_id)
    vetted_external_ids = _leaf_bound_ids(tree["nodes"])
    return {
        node_key: {"external_id": row["external_id"],
                    "source_tree_task_id": row["source_tree_task_id"]}
        for node_key, row in raw.items()
        if row["source_tree_task_id"] is not None
        and vetted_external_ids.get(node_key) == row["external_id"]
    }


def _coordinate_labels(conn, org_id: str, brand_id: str) -> dict:
    """`(dimension, key) → label`，供把候選存的 key 轉成使用者看得懂的中文名稱。讀
    `list_coordinates()`（跟品牌智庫「創意座標」分頁同一支既有讀取，不另開一條）。"""
    return {
        (c["dimension"], c["key"]): c["label"]
        for c in schedule_repo.list_coordinates(conn, org_id, brand_id)
    }


def _bucket(rows: list) -> dict:
    """一組花費列（一個座標值，或 `未標座標`）→ 畫面要的六個聚合數字，外加 `ad_count`。
    `revenue`／`roas` 只用有追蹤到 `roas` 的那些列（ADR 0057 §7），`roas_coverage` 用**這
    整組**列數當分母——一列是一個實體一天，不是一個廣告。"""
    spend = sum(r["spend"] for r in rows)
    with_roas = [r for r in rows if r["roas"] is not None]
    revenue: float | None = None
    roas: float | None = None
    if with_roas:
        spend_with_roas = sum(r["spend"] for r in with_roas)
        revenue = sum(r["spend"] * r["roas"] for r in with_roas)
        roas = (revenue / spend_with_roas) if spend_with_roas else None
    return {
        "spend": round(spend, 2),
        "impressions": sum(r["impressions"] for r in rows),
        "clicks": sum(r["clicks"] for r in rows),
        "revenue": round(revenue, 2) if revenue is not None else None,
        # roas／roas_coverage 是比率，不是錢——比照 spend_summary 既有慣例（ctr／cpc／cpm
        # 也不在 Python 端 round()），原始精度直接穿出去，畫面自己決定顯示幾位。
        "roas": roas,
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


def _currency_view(currency: str, rows: list, entity_candidate: dict, labels: dict) -> dict:
    total_spend = round(sum(r["spend"] for r in rows), 2)
    reaches_any = {
        entity_id: bool(candidate and any(candidate.get(f"{d}_key") for d in COORDINATE_KEYS))
        for entity_id, candidate in entity_candidate.items()
    }
    currency_untagged_rows = [r for r in rows if not reaches_any.get(r["entity_id"], False)]

    dimensions = []
    for dimension in COORDINATE_KEYS:
        column = f"{dimension}_key"
        buckets: dict = {}
        for row in rows:
            candidate = entity_candidate.get(row["entity_id"])
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
    entity_to_slot = {b["external_id"]: (node_key, b["source_tree_task_id"])
                       for node_key, b in vetted.items()}
    candidates = schedule_repo.creative_candidates_for_brand(conn, org_id, brand_id)
    entity_candidate = {
        entity_id: candidates.get(slot) for entity_id, slot in entity_to_slot.items()
    }
    labels = _coordinate_labels(conn, org_id, brand_id)

    rows_by_currency: dict = {}
    for row in daily_rows:
        rows_by_currency.setdefault(row["currency"], []).append(row)

    currencies = [
        _currency_view(currency, rows, entity_candidate, labels)
        for currency, rows in sorted(rows_by_currency.items())
    ]

    return {
        "window": {
            "start_date": month_start.isoformat(),
            "end_date": (month_end - timedelta(days=1)).isoformat(),
        },
        "currencies": currencies,
    }
