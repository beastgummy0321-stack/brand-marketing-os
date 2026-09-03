"""app/schedule/tree.py — 純函數：把選定的一個方案展開成三層活動樹（票 09）。

Private to app/schedule/（集裝箱憲章第一節）：只有 app/schedule/routes.py 呼叫這裡的函式，
外面任何模組都不 import 這個檔案。

票 09 settled 段：
1. 沒有新表、沒有 migration。樹跟方案一樣是第二列 `llm_task`（`task_type = "schedule_tree"`），
   每次讀都從 `rendered_output` 重新算（`structured_output_json` 不落地）——完全比照
   `plan.py` 的 `plan_from_task_row`。
4. 代理回覆的 JSON 契約（回覆最後一個 fenced json block）：
   `{"levels": [3 個字串], "budget_level": <1-based int>, "nodes": [...]}`——`levels` 是
   平台自己對三層的叫法，外殼從不寫死；`budget_level` 指出哪一層扛預算（Meta＝2、
   Google＝1，資料不是常數）。剛好三層深；`budget_level` 那一層的節點 `share` 落在
   (0, 1]，其他層一律 `null`。
5. 錢的算法是外殼唯一會拒絕的地方：照文件順序蒐集所有扛 `share` 的節點，總和跟 1.0
   誤差超過既有 `_SHARE_SUM_TOLERANCE` 就整棵樹失敗——重用 `plan.py` 的
   `largest_remainder_allocation()`／`_extract_last_json_block()`，不重寫第二份。
   `_SHARE_SUM_TOLERANCE` 是 IEEE-754 加總誤差，不是商業容忍值，不得調寬（沿用 plan.py
   的既有常數，這裡不重新定義）。失敗訊息不沿用 `plan.py` 的 `BAD_SHARES_MESSAGE`——那句話
   叫使用者「請重新排程一次」，但這裡失敗時使用者該做的是重新展開，不是重新排程一整批方案
   （票 10-feedback-entries 帶著票 09 review 的小修正，見票 10 settled 段第 6 點）。
"""

from app.schedule.plan import (
    _SHARE_SUM_TOLERANCE,
    _extract_last_json_block,
    largest_remainder_allocation,
)

NO_TREE_MESSAGE = "代理沒有回傳看得懂的活動結構，請重新展開一次。"
NO_REPLY_MESSAGE = "展開失敗，請重新展開一次。"
BAD_SHARES_MESSAGE = "方案裡的比例加起來不是 100%，請重新展開一次。"


def _valid_fields(raw_fields) -> list[dict] | None:
    """`fields` 清單驗證：每個元素是 `{"label": str, "value": str}`。"""
    if not isinstance(raw_fields, list):
        return None
    fields = []
    for item in raw_fields:
        if not isinstance(item, dict):
            return None
        label, value = item.get("label"), item.get("value")
        if not isinstance(label, str) or not isinstance(value, str):
            return None
        fields.append({"label": label, "value": value})
    return fields


def _valid_warnings(raw_warnings) -> list[str] | None:
    """`warnings` 清單驗證：純字串清單，空清單＝這個節點跟平台預設一致。"""
    if not isinstance(raw_warnings, list) or not all(isinstance(w, str) for w in raw_warnings):
        return None
    return list(raw_warnings)


def _collect_nodes(
    raw_nodes, depth: int, budget_level: int, share_bucket: list, parent_key: str
) -> list[dict] | None:
    """驗一層節點，遞迴驗子節點；扛 `share` 的節點依文件（深度優先、前序）順序塞進
    `share_bucket`，供 `build_tree` 統一算錢——票 09 settled 段第 5 點「照文件順序蒐集」。
    `depth` 從 1 開始對齊 `budget_level` 的 1-based 編號；第三層不得再有子節點（剛好三層深）。

    `node_key`（票 T3b，ADR 0055 §1）是同一個深度優先前序順序算出來的路徑：1-based、
    點分隔，`parent_key` 是上一層算好的前綴（根層是空字串）。這是節點在整棵樹的唯一
    識別，`channel_entity_map` 拿它當鍵；同輸入同輸出，不落地、每次讀都重算。
    """
    if not isinstance(raw_nodes, list) or not raw_nodes:
        return None

    nodes = []
    for index, raw in enumerate(raw_nodes, start=1):
        node_key = f"{parent_key}.{index}" if parent_key else str(index)
        if not isinstance(raw, dict):
            return None
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            return None
        fields = _valid_fields(raw.get("fields", []))
        if fields is None:
            return None
        warnings = _valid_warnings(raw.get("warnings", []))
        if warnings is None:
            return None

        raw_share = raw.get("share")
        if depth == budget_level:
            if isinstance(raw_share, bool) or not isinstance(raw_share, (int, float)):
                return None
            share = float(raw_share)
            if not (0 < share <= 1):
                return None
        else:
            if raw_share is not None:
                return None
            share = None

        if depth == 3:
            if raw.get("children") not in ([], None):
                return None
            children = []
        else:
            deeper = _collect_nodes(
                raw.get("children"), depth + 1, budget_level, share_bucket, node_key
            )
            if deeper is None:
                return None
            children = deeper

        node = {
            "name": name, "node_key": node_key, "fields": fields, "share": share,
            "daily_amount": None, "warnings": warnings, "children": children,
            # tree.py 不碰 DB，一律留白；只有第一層節點會被 routes.py 的
            # _tree_with_bindings() 疊上 bound_external_id（第一層以下永遠是
            # null——T3b 只綁第一層，ADR 0055 §7），spend／roas 只有綁定的節點才補上。
            "bound_external_id": None, "spend": None, "roas": None,
        }
        if depth == budget_level:
            share_bucket.append(node)
        nodes.append(node)
    return nodes


def build_tree(rendered_output: str, daily_budget: float) -> tuple[dict, str | None]:
    """代理回覆 → (tree_body, failure)。失敗時 tree_body 是 `{}`；成功時是
    `{"levels", "budget_level", "nodes"}`（`task_id`／`created_at`／`plan_index`／`narrative`
    是呼叫端 `tree_from_task_row()` 補的殼層欄位，不在這裡算）。"""
    data = _extract_last_json_block(rendered_output)
    if data is None:
        return {}, NO_TREE_MESSAGE

    levels = data.get("levels")
    if (not isinstance(levels, list) or len(levels) != 3
            or not all(isinstance(name, str) and name for name in levels)):
        return {}, NO_TREE_MESSAGE

    budget_level = data.get("budget_level")
    if isinstance(budget_level, bool) or budget_level not in (1, 2, 3):
        return {}, NO_TREE_MESSAGE
    budget_level = int(budget_level)

    share_bucket: list[dict] = []
    nodes = _collect_nodes(data.get("nodes"), 1, budget_level, share_bucket, "")
    if nodes is None or not share_bucket:
        return {}, NO_TREE_MESSAGE

    shares = [node["share"] for node in share_bucket]
    if abs(sum(shares) - 1.0) > _SHARE_SUM_TOLERANCE:
        return {}, BAD_SHARES_MESSAGE

    amounts = largest_remainder_allocation(round(daily_budget), shares)
    for node, amount in zip(share_bucket, amounts, strict=True):
        node["daily_amount"] = amount

    return {"levels": levels, "budget_level": budget_level, "nodes": nodes}, None


def tree_from_task_row(row: dict) -> dict:
    """把一列 `llm_task`（`task_type = "schedule_tree"`）轉成 API 回傳的 `tree` 形狀——
    GET／POST 回傳同一個形狀，且對同一列每次呼叫都算出一樣的結果（比照
    `plan.plan_from_task_row`：`structured_output_json` 不落地，從 `rendered_output`
    逐次重算，同輸入同輸出）。

    `context_scope_json.daily_budget` 是路由層在建這列時，從選定方案的來源 `llm_task`
    列凍結進來的預算（票 09 settled 段第 6 點），不是這裡重讀規則卡——樹要跟使用者選
    的那張方案卡一致，不是跟當下的規則卡設定一致。"""
    scope = row.get("context_scope_json") or {}
    daily_budget = scope.get("daily_budget", 0)
    plan_index = scope.get("plan_index", 0)
    rendered_output = row.get("rendered_output") or ""

    # 2026-08-29：`running` 不是失敗。原本這裡把「還在跑」也算進失敗分支，而執行中的列
    # `error` 是 NULL，於是使用者看到「請重新一次」——一按又開一個 running，永遠回不到
    # 已經算好的結果。呼叫端靠 `running` 決定要顯示進行中還是失敗。
    running = row["status"] == "running"
    if row["status"] != "succeeded":
        failure = None if running else (row.get("error") or NO_REPLY_MESSAGE)
        body: dict = {}
    else:
        body, failure = build_tree(rendered_output, daily_budget)

    # 票 T3b（ADR 0055 §4）：綁定不再從這一列自己的 context_scope_json 讀——這是純函數，
    # 沒有連線，讀不到 channel_entity_map。bound_external_id 一律是 null；填值是呼叫端
    # `routes._tree_with_bindings()` 的事。
    return {
        "task_id": row["id"],
        "created_at": row["started_at"],
        "plan_index": plan_index,
        "levels": body.get("levels", []),
        "budget_level": body.get("budget_level"),
        "nodes": body.get("nodes", []),
        "narrative": rendered_output,
        "failure": failure,
        "running": running,
        # settled 段第 7 點：這個欄位只在 POST .../tree/bind 的回應裡非空，GET／
        # plan／tree／reject 一律 null，且從不落地——routes.py 的 bind 路由算完之後才
        # 蓋上這個值。
        "bind_failure": None,
    }
