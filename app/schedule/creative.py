"""app/schedule/creative.py — 純函數：把已展開的活動樹每個最深層節點各配一份內容
（`.scratch/creative-slice/issues/01-ad-creative-per-ad-node.md`）。

Private to app/schedule/（集裝箱憲章第一節）：只有 app/schedule/routes.py 呼叫這裡的函式，
外面任何模組都不 import 這個檔案。

票 01 settled 段：
1. 沒有新表、沒有 migration。跟 plan／tree 一樣，這是第三列 `llm_task`
   （`task_type = "schedule_creative"`），每次讀都從 `rendered_output` 重新算
   （`structured_output_json` 不落地）——完全比照 `plan.py` 的 `plan_from_task_row`。
2. 代理回覆的 json 契約（回覆最後一個 fenced json block）：
   `{"creatives": [{"node", "coordinates", "fields": [{"label","value"}], "warnings": [str]}]}`
   ——`label` 是部門任務檔（`app/departments/creative/ad_creative.md`）的決定，這支函式只
   搬動，不認得任何一個具體欄位名稱（frozen decision 3：外殼不懂通路或這個部門自己的詞彙）。
3. 綁定規則跟票 11 同精神：`node` 必須逐一對上樹裡每個最深層節點的確切名稱，缺一個、多
   一個、或名稱對不上樹，整批失敗，不猜、不局部渲染（frozen decision 4）。

票 T1（`docs/issues/T1-creative-fingerprint/ticket.md`）：decision 3 收窄，不是拿掉——外殼
還是不懂 `fields` 裡的欄位名稱，但多認得一個固定的手足鍵 `coordinates`：
`CONSTITUTION.md` 規則 5 簽下的七個維度名稱（見 `COORDINATE_KEYS`），值是非空字串或
`null`，這裡不查詞彙表（vocabulary 驗證留給 T1b，還沒有表）。同一張票也把 `fields` 的
`value` 從純字串放寬成 `string | string[]`（`app/methodology/meta-format-specs.md` 要求
5 個變體，單一字串會丟掉 4 個）——`tree.py` 的 `_valid_fields` 本身不動，它跟
`_collect_nodes` 共用，改了會連動改到活動樹自己的欄位契約；這裡另外寫一支
`_valid_creative_fields`。

`creative_from_task_row(row, ad_node_names)` 比 `tree_from_task_row(row)` 多吃一個參數：
`plan`／`tree` 的合法性只看自己那份回覆（比例加總、層數），但這裡的合法性還要看「當初凍結
的那棵樹」有哪些最深層節點——這份清單不落在 `context_scope_json`（frozen decision 5 的
字面契約只有三個鍵），呼叫端（`routes.py`）必須自己重讀那筆凍結的 `source_tree_task_id`
再算一次，這支函式本身仍然不碰 DB。
"""

from app.schedule.plan import _extract_last_json_block
from app.schedule.tree import _valid_warnings

NO_CREATIVE_MESSAGE = "代理沒有回傳看得懂的內容，請重新產出一次。"
NODE_MISMATCH_MESSAGE = "內容的節點名稱跟活動樹對不起來，請重新產出一次。"
NO_REPLY_MESSAGE = "產出失敗，請重新產出一次。"

# `CONSTITUTION.md` 規則 5 簽下的七個維度名稱，逐字沿用，這支模組不定義任何別的名字。
COORDINATE_KEYS = ("audience", "pain", "angle", "hook", "proof", "offer", "format")


def _valid_coordinates(raw) -> dict:
    """`coordinates`：值是非空字串或 `null`，不查詞彙表（T1b 才有表）。缺這個鍵、整個
    `coordinates` 給錯形狀（list／字串）、或個別維度給錯形狀（`""`、數字）——座標是診斷用
    中繼資料不是交付物，壞值一律退回該維度 `null`，不讓文案跟著整批作廢（票 T1 站③收尾）。
    鍵之外的名字丟棄，跟 `fields` 裡認不得的鍵一樣不算錯，不是這裡的合法性範圍。"""
    if not isinstance(raw, dict):
        return {key: None for key in COORDINATE_KEYS}
    result: dict = {}
    for key in COORDINATE_KEYS:
        value = raw.get(key)
        result[key] = value if (value is None or (isinstance(value, str) and value)) else None
    return result


def _valid_creative_fields(raw_fields) -> list[dict] | None:
    """`fields` 清單驗證，跟 `tree._valid_fields` 只差一點：`value` 收 `string | string[]`，
    一律正規化成陣列——單一字串正規化成單元素陣列，既有的單字串回覆照樣能用。"""
    if not isinstance(raw_fields, list):
        return None
    fields = []
    for item in raw_fields:
        if not isinstance(item, dict):
            return None
        label, value = item.get("label"), item.get("value")
        if not isinstance(label, str):
            return None
        if isinstance(value, str):
            values = [value]
        elif isinstance(value, list) and all(isinstance(v, str) for v in value):
            values = value
        else:
            return None
        fields.append({"label": label, "value": values})
    return fields


def build_creative(rendered_output: str, ad_node_names: list[str]) -> tuple[list[dict], str | None]:
    """代理回覆 → (ads, failure)。失敗時 ads 是 `[]`；成功時每個元素是
    `{"node", "coordinates", "fields", "warnings"}`，順序照 `ad_node_names`（樹的文件順序），
    不是代理回覆裡的順序——代理不保證照樹的順序回覆。"""
    data = _extract_last_json_block(rendered_output)
    if data is None:
        return [], NO_CREATIVE_MESSAGE

    raw_creatives = data.get("creatives")
    if not isinstance(raw_creatives, list) or not raw_creatives:
        return [], NO_CREATIVE_MESSAGE

    by_node: dict[str, dict] = {}
    for item in raw_creatives:
        if not isinstance(item, dict):
            return [], NO_CREATIVE_MESSAGE
        node = item.get("node")
        if not isinstance(node, str) or not node:
            return [], NO_CREATIVE_MESSAGE
        coordinates = _valid_coordinates(item.get("coordinates"))
        fields = _valid_creative_fields(item.get("fields", []))
        if fields is None:
            return [], NO_CREATIVE_MESSAGE
        warnings = _valid_warnings(item.get("warnings", []))
        if warnings is None:
            return [], NO_CREATIVE_MESSAGE
        if node in by_node:
            return [], NODE_MISMATCH_MESSAGE  # 同一個節點回了兩份，不猜哪一份才對
        by_node[node] = {
            "node": node, "coordinates": coordinates, "fields": fields, "warnings": warnings,
        }

    if set(by_node) != set(ad_node_names):
        return [], NODE_MISMATCH_MESSAGE  # 少一個、多一個、或名稱對不上樹

    ads = [by_node[name] for name in ad_node_names]
    return ads, None


def creative_from_task_row(row: dict, ad_node_names: list[str]) -> dict:
    """把一列 `llm_task`（`task_type = "schedule_creative"`）轉成 API 回傳的 `creative`
    形狀——GET／POST 回傳同一個形狀，且對同一個 `(row, ad_node_names)` 每次呼叫都算出一樣
    的結果（比照 `plan.plan_from_task_row`：`structured_output_json` 不落地，從
    `rendered_output` 逐次重算，同輸入同輸出）。`ad_node_names` 由呼叫端重讀這一列凍結的
    `source_tree_task_id` 現算——frozen decision 5：核對用的永遠是產出當下的那棵樹，使用者
    之後重新展開樹不會悄悄改寫已經產出的內容。"""
    scope = row.get("context_scope_json") or {}
    rendered_output = row.get("rendered_output") or ""

    # 2026-08-29（沿用 tree_from_task_row 的既有教訓）：`running` 不是失敗，呼叫端靠這個
    # 欄位決定要顯示進行中還是失敗，不會把「還在跑」誤判成「請重新一次」。
    running = row["status"] == "running"
    if row["status"] != "succeeded":
        failure = None if running else (row.get("error") or NO_REPLY_MESSAGE)
        ads: list[dict] = []
    else:
        ads, failure = build_creative(rendered_output, ad_node_names)

    return {
        "task_id": row["id"],
        "created_at": row["started_at"],
        "source_tree_task_id": scope.get("source_tree_task_id"),
        "ads": ads,
        "narrative": rendered_output,
        "failure": failure,
        "running": running,
    }
