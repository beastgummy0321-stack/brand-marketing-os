"""app/schedule/plan.py — 純函數：從代理回覆抽方案、money 由這裡的程式算（票 07）。

Private to app/schedule/（集裝箱憲章第一節）：只有 app/schedule/routes.py 呼叫這裡的函式，
外面任何模組都不 import 這個檔案。

票 07 settled 段「代理的回覆——字面契約」：
1. 抓 rendered_output 裡『最後一個』fenced json block，`json.loads`；沒有區塊、JSON 壞掉、
   或沒有 `splits` 清單都算失敗。
2. 每個 `share` 必須是 (0, 1] 之間的實數；比例總和與 1.0 誤差超過 `_SHARE_SUM_TOLERANCE`
   算失敗——這個誤差是 IEEE-754 加總小數字面值的浮點誤差（`0.7 + 0.3 ==
   0.9999999999999999`），不是商業容忍值，不得調寬。
3. `daily_amount` 用最大餘數法把 `round(daily_budget)` 整數元分給每個方向，總和精確等於
   `round(daily_budget)`。
4. `label`／`why` 是代理自己的文字，原樣呈現；這裡只算錢。
"""

import json
import re

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)

# 浮點誤差，非商業容忍值：見票 07 settled 段「來源：IEEE-754 slack」。不得調寬。
_SHARE_SUM_TOLERANCE = 1e-6

BUDGET_NOT_SET_MESSAGE = "請先到設定頁填「檔期日預算」，再回來排程。"
NO_PLAN_MESSAGE = "代理沒有回傳看得懂的方案內容，請重新排程一次。"
BAD_SHARES_MESSAGE = "方案裡的比例加起來不是 100%，請重新排程一次。"
NO_REPLY_MESSAGE = "排程失敗，請重新排程一次。"


def _extract_last_json_block(rendered_output: str) -> dict | None:
    """抓『最後一個』fenced json block 並解析；缺區塊或解析失敗一律回 None，不拋例外。"""
    matches = _JSON_BLOCK_RE.findall(rendered_output or "")
    if not matches:
        return None
    try:
        parsed = json.loads(matches[-1])
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_shares(raw_splits: list) -> list[float] | None:
    """驗每個方向的 `share` 是 (0, 1] 之間的實數；任何一個不合法就整批失敗（回 None）。"""
    shares = []
    for item in raw_splits:
        if not isinstance(item, dict):
            return None
        share = item.get("share")
        if isinstance(share, bool) or not isinstance(share, (int, float)):
            return None
        share = float(share)
        if not (0 < share <= 1):
            return None
        shares.append(share)
    return shares


def largest_remainder_allocation(total: int, shares: list[float]) -> list[int]:
    """最大餘數法：把 `total`（整數元）依 `shares` 分配成整數金額，加總永遠精確等於
    `total`（票 07 settled 段第 4 點）。"""
    scaled = [total * share for share in shares]
    base = [int(x) for x in scaled]  # 非負值的 int() 等同 floor
    remainder = total - sum(base)
    order = sorted(range(len(shares)), key=lambda i: scaled[i] - base[i], reverse=True)
    for i in order[:remainder]:
        base[i] += 1
    return base


def build_splits(rendered_output: str, daily_budget: float) -> tuple[list[dict], str | None]:
    """代理回覆 → (splits, failure)。失敗時 splits 是 `[]`，failure 是人話句子；
    成功時 failure 是 None（GET／POST 共用這個轉換，見 plan_from_task_row）。"""
    data = _extract_last_json_block(rendered_output)
    raw_splits = data.get("splits") if data is not None else None
    if not isinstance(raw_splits, list) or not raw_splits:
        return [], NO_PLAN_MESSAGE

    shares = _parse_shares(raw_splits)
    if shares is None:
        return [], NO_PLAN_MESSAGE
    if abs(sum(shares) - 1.0) > _SHARE_SUM_TOLERANCE:
        return [], BAD_SHARES_MESSAGE

    amounts = largest_remainder_allocation(round(daily_budget), shares)
    splits = [
        {
            "label": str(item.get("label", "")),
            "share": share,
            "why": str(item.get("why", "")),
            "daily_amount": amount,
        }
        for item, share, amount in zip(raw_splits, shares, amounts, strict=True)
    ]
    return splits, None


def plan_from_task_row(row: dict) -> dict:
    """把一列 `llm_task` 轉成 API 回傳的 `plan` 形狀——GET／POST 回傳同一個形狀，且對同一列
    每次呼叫都算出一樣的結果（`structured_output_json` 不落地，票 07 settled 段：方案從
    `rendered_output` 逐次重算，同輸入同輸出）。"""
    scope = row.get("context_scope_json") or {}
    daily_budget = scope.get("daily_budget", 0)
    product_ids = scope.get("product_ids", [])
    rendered_output = row.get("rendered_output") or ""

    if row["status"] != "succeeded":
        failure = row.get("error") or NO_REPLY_MESSAGE
        splits: list[dict] = []
    else:
        splits, failure = build_splits(rendered_output, daily_budget)

    return {
        "task_id": row["id"],
        "created_at": row["started_at"],
        "product_ids": product_ids,
        "daily_budget": daily_budget,
        "narrative": rendered_output,
        "splits": splits,
        "failure": failure,
    }
