"""app/schedule/plan.py — 純函數：從代理回覆抽方案、money 由這裡的程式算（票 07／08）。

Private to app/schedule/（集裝箱憲章第一節）：只有 app/schedule/routes.py 呼叫這裡的函式，
外面任何模組都不 import 這個檔案。

票 07 settled 段「代理的回覆——字面契約」，票 08 把單一方案擴成 N 個方案：
1. 抓 rendered_output 裡『最後一個』fenced json block，`json.loads`；沒有區塊、JSON 壞掉、
   或沒有 `plans` 清單都算失敗。`plans` 底下每個元素各自是一個方案（`summary`／`reasoning`／
   `splits`），任何一個方案驗證失敗，整批失敗（票 08 沿用票 07「整批失敗」的規則，不挑好的
   留、壞的丟）。
2. 每個方案裡每個 `share` 必須是 (0, 1] 之間的實數；同一個方案裡比例總和與 1.0 誤差超過
   `_SHARE_SUM_TOLERANCE` 算失敗——這個誤差是 IEEE-754 加總小數字面值的浮點誤差（`0.7 + 0.3
   == 0.9999999999999999`），不是商業容忍值，不得調寬。
3. `daily_amount` 用最大餘數法把 `round(daily_budget)` 整數元分給每個方向，總和精確等於
   `round(daily_budget)`——每個方案各自分一次，用的是同一份日預算。
4. `summary`／`reasoning`／`label`／`why` 都是代理自己的文字，原樣呈現；這裡只算錢。
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


def _build_splits_from_raw(raw_splits, daily_budget: float) -> tuple[list[dict], str | None]:
    """`splits` 原始清單 → (splits, failure)。單一方案的驗證核心，票 07 就有，票 08 原樣重用
    ——每個方案各跑一次，不重寫第二套share/最大餘數邏輯。"""
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


def _build_one_plan(item, daily_budget: float) -> tuple[dict | None, str | None]:
    """`plans` 底下一個元素 → (方案 dict, failure)。失敗時方案是 None。"""
    if not isinstance(item, dict):
        return None, NO_PLAN_MESSAGE
    splits, failure = _build_splits_from_raw(item.get("splits"), daily_budget)
    if failure is not None:
        return None, failure
    return {
        "summary": str(item.get("summary", "")),
        "reasoning": str(item.get("reasoning", "")),
        "splits": splits,
    }, None


def build_plans(rendered_output: str, daily_budget: float) -> tuple[list[dict], str | None]:
    """代理回覆 → (plans, failure)（票 08：N 個方案，取代票 07 的單一 `splits`）。失敗時
    plans 是 `[]`，failure 是人話句子；成功時 failure 是 None。任何一個方案驗證失敗，
    整批失敗——不挑好的留、壞的丟（沿用票 07「整批失敗」的規則）。"""
    data = _extract_last_json_block(rendered_output)
    raw_plans = data.get("plans") if data is not None else None
    if not isinstance(raw_plans, list) or not raw_plans:
        return [], NO_PLAN_MESSAGE

    plans = []
    for item in raw_plans:
        one, failure = _build_one_plan(item, daily_budget)
        if failure is not None:
            return [], failure
        plans.append(one)
    return plans, None


def plan_from_task_row(row: dict) -> dict:
    """把一列 `llm_task` 轉成 API 回傳的 `plan` 形狀——GET／POST 回傳同一個形狀，且對同一列
    每次呼叫都算出一樣的結果（`structured_output_json` 不落地，票 07 settled 段：方案從
    `rendered_output` 逐次重算，同輸入同輸出；票 08 沿用同一個設計，N 個方案一樣逐次重算）。

    `sources` 讀自 `usage_json.search_sources`（票 08：`app/llm/providers.py` 在網路搜尋
    成功時填的欄位，見該檔 `AnthropicProvider.complete()`）——搜尋沒開、沒結果、或搜尋本身
    出錯，這裡一律是空清單，不當成排程失敗（票 08 兩條不可妥協規則第 1 條：查詢不是排程的
    先決條件）。"""
    scope = row.get("context_scope_json") or {}
    daily_budget = scope.get("daily_budget", 0)
    product_ids = scope.get("product_ids", [])
    platform = scope.get("platform", "")
    objective = scope.get("objective", "")
    promotion_note = scope.get("promotion_note", "")
    rendered_output = row.get("rendered_output") or ""
    usage = row.get("usage_json") or {}
    sources = usage.get("search_sources") or []

    # 2026-08-29：`running` 不是失敗。原本這裡把「還在跑」也算進失敗分支，而執行中的列
    # `error` 是 NULL，於是使用者看到「請重新一次」——一按又開一個 running，永遠回不到
    # 已經算好的結果。呼叫端靠 `running` 決定要顯示進行中還是失敗。
    running = row["status"] == "running"
    if row["status"] != "succeeded":
        failure = None if running else (row.get("error") or NO_REPLY_MESSAGE)
        plans: list[dict] = []
    else:
        plans, failure = build_plans(rendered_output, daily_budget)

    return {
        "task_id": row["id"],
        "created_at": row["started_at"],
        "product_ids": product_ids,
        "daily_budget": daily_budget,
        "platform": platform,
        "objective": objective,
        "promotion_note": promotion_note,
        "narrative": rendered_output,
        "plans": plans,
        "sources": sources,
        "failure": failure,
        "running": running,
    }
