"""app/core/orchestrator.py — 調度台本體（票 O1-01，ADR 0024）。

`decide(facts) -> [Action]`：純函數，規則登記制（照抄 `app/dashboard/guide_cards.py`
的 `RULES` 寫法）。`run(conn, brand_id, *, actor) -> dict`：派工員，收集各登記模組的
`status()` 組成一包 facts → `decide()` → 自動度閘門 → 執行或出卡 → 寫 `decision` 表留痕。

**唯一進入點在這裡**：本檔不 import 任何模組內部任何東西（ADR 0024 決議 1、2、7；
container-contract「唯一進入點」）。各模組反過來在自己的檔案尾巴呼叫
`register_module()`／`register_rule()` 把自己掛進來——比照 `app/core/cleanup.py` 的
登記制，本檔完全不知道任何模組的業務邏輯，模組被拔掉時只是 facts 少幾個 key、
規則讀不到就 `facts.get(...)` 回 None 安靜降級。

自動度閘門單一收口在這裡（ADR 0024 決議 8）：讀 `rule_cards.py` 的 autonomy（1.0 保守／
2.0 放手）× `action.risk` 決定「直接呼叫 handle()」或「寫 decision 列＋出卡等同意」。
**模組永遠不知道有沒有人核可過，也不得自己判斷要不要問使用者。**

錯誤邊界（ADR 0024 決議 5，比照 `app/ads/auto_sync.py:93`）：每個 Action 各自
try/except，一個炸掉不擋其他；`spend` 級失敗立刻出卡，`save`／`asset` 級只寫
`decision`、下一輪自動重試；同一 `dedupe_key` 連續失敗滿 3 次，不分風險級一律升級出卡。

去重：同一 `dedupe_key` 已有一列 `outcome` 為 `auto_done` 或 `carded` → 跳過不重做。
"""

from collections.abc import Callable

from app.core import cleanup, rule_cards
from app.core import interrupts as core_interrupts
from app.core.db import jsonb, new_id, now_utc

# 登記表：模組在自己的檔案尾巴呼叫 register_module()／register_rule() 掛進來，
# 本檔本身永遠是空字典起家（比照 app/core/cleanup.py 的 _REGISTRY）。
MODULES: dict = {}
RULES: dict = {}

# rule_cards.py CARDS["autonomy"]["fields"]["mode"]：1.0 保守檔／2.0 放手檔。
_AUTONOMY_HANDSOFF = 2.0
# 同一 dedupe_key 連續失敗達這個次數，不分風險級一律升級出卡（ADR 0024 決議 5）。
_MAX_ATTEMPTS_BEFORE_ESCALATION = 3

# 調度台自己的打斷佇列類別：出卡等同意、連續失敗升級都走這一類，固定短句不塞動態內容
# （比照 app/ads/auto_sync.py 的 _META_FAILURE_MESSAGE 寫法），訊息 ≤30 全形字上限見
# app/core/interrupts.py MAX_MESSAGE_LEN。
_CARD_CATEGORY = "orchestrator_pending"
_CARDED_MESSAGE = "有動作要你核可，去確認一下"
_ESCALATED_MESSAGE = "自動執行連續失敗，麻煩看一下"


def register_module(name: str, *, status: Callable, handle: Callable) -> None:
    """模組登記自己的公開面。同一個 name 不能重複登記（打字錯誤／重複掛載當場報錯，
    比照 cleanup.register()）。"""
    if not name or status is None or handle is None:
        raise ValueError("register_module() 的 name、status、handle 都是必填")
    if name in MODULES:
        raise ValueError(f"「{name}」已經登記過調度台模組了，不能重複登記")
    MODULES[name] = {"status": status, "handle": handle}


def register_rule(rule_id: str, rule: "Callable[[dict], dict | None]") -> None:
    """模組登記一條規則。規則歸屬看「這條規則叫誰做事」，登記在被叫的那個模組的檔案裡
    （ADR 0024 決議 7），不是登記在調度台本身。"""
    if not rule_id or rule is None:
        raise ValueError("register_rule() 的 rule_id、rule 都是必填")
    if rule_id in RULES:
        raise ValueError(f"「{rule_id}」已經登記過調度台規則了，不能重複登記")
    RULES[rule_id] = rule


def decide(facts: dict) -> list:
    """純函數：一包 facts → [Action]。依登記順序掃過全部規則；不碰資料庫、不呼叫任何
    模組的 handle()。同一包 facts 呼叫兩次必須產出相同結果。"""
    actions = []
    for rule_id, rule in RULES.items():
        action = rule(facts)
        if action is not None:
            actions.append({**action, "rule_id": rule_id})
    return actions


def _get_decision(conn, brand_id: str, dedupe_key: str) -> "dict | None":
    row = conn.execute(
        "SELECT * FROM decision WHERE brand_id = %s AND dedupe_key = %s",
        (brand_id, dedupe_key),
    ).fetchone()
    return dict(row) if row is not None else None


def _insert_decision(conn, *, org_id: str, brand_id: str, module: str, rule_id: str, action_json,
                     risk_level: str, autonomy_mode: float, dedupe_key: str, outcome: str,
                     attempt_count: int, error_text: "str | None") -> str:
    decision_id = new_id("dcs")
    ts = now_utc()
    conn.execute(
        "INSERT INTO decision (id, org_id, module, brand_id, rule_id, action_json, risk_level,"
        " autonomy_mode, dedupe_key, outcome, attempt_count, error_text, created_at,"
        " updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (decision_id, org_id, module, brand_id, rule_id, action_json, risk_level, autonomy_mode,
         dedupe_key, outcome, attempt_count, error_text, ts, ts),
    )
    return decision_id


def _update_decision(conn, decision_id: str, *, outcome: str, attempt_count: int,
                     error_text: "str | None") -> None:
    """事實欄（module／brand_id／rule_id／action_json／risk_level／autonomy_mode／
    created_at）寫入後不動；只更新狀態欄（outcome／attempt_count／error_text，2026-08-23
    更正版，見 ADR 0024）。"""
    conn.execute(
        "UPDATE decision SET outcome = %s, attempt_count = %s, error_text = %s, updated_at = %s"
        " WHERE id = %s",
        (outcome, attempt_count, error_text, now_utc(), decision_id),
    )


def _process_action(conn, org_id: str, brand_id: str, action: dict) -> dict:
    """單一 Action 的閘門＋執行＋留痕，各自 try/except，一個炸掉不擋其他。"""
    dedupe_key = action["dedupe_key"]
    module_name = action["module"]
    rule_id = action["rule_id"]
    risk = action.get("risk")
    risk_level = risk or "none"  # DDL risk_level 是 NOT NULL；「risk 無」存成字面 "none"

    existing = _get_decision(conn, brand_id, dedupe_key)
    if existing is not None and existing["outcome"] in ("auto_done", "carded"):
        return {"dedupe_key": dedupe_key, "outcome": existing["outcome"], "skipped": True}

    autonomy_mode = rule_cards.get_value(conn, brand_id, "autonomy", "mode")
    action_json = jsonb(action)

    def _write(outcome: str, attempt_count: int, error_text: "str | None") -> str:
        if existing is None:
            return _insert_decision(
                conn, org_id=org_id, brand_id=brand_id, module=module_name, rule_id=rule_id,
                action_json=action_json, risk_level=risk_level, autonomy_mode=autonomy_mode,
                dedupe_key=dedupe_key, outcome=outcome, attempt_count=attempt_count,
                error_text=error_text)
        _update_decision(conn, existing["id"], outcome=outcome, attempt_count=attempt_count,
                         error_text=error_text)
        return existing["id"]

    # 自動度閘門單一收口：risk 無＝一律自動做；否則放手檔（>=2.0）才自動做，保守檔出卡。
    if risk and autonomy_mode < _AUTONOMY_HANDSOFF:
        decision_id = _write("carded", 1, None)
        core_interrupts.enqueue(
            conn, org_id=org_id, category=_CARD_CATEGORY, brand_id=brand_id,
            dedupe_key=f"decision:{decision_id}", message=_CARDED_MESSAGE,
        )
        return {"dedupe_key": dedupe_key, "outcome": "carded", "decision_id": decision_id}

    attempt_count = (existing["attempt_count"] + 1) if existing else 1
    try:
        MODULES[module_name]["handle"](conn, action)
    except Exception as exc:  # noqa: BLE001 — 一個 Action 炸掉不擋其他（ADR 0024 決議 5）
        error_text = str(exc)
        decision_id = _write("failed", attempt_count, error_text)
        if risk == "spend" or attempt_count >= _MAX_ATTEMPTS_BEFORE_ESCALATION:
            core_interrupts.enqueue(
                conn, org_id=org_id, category=_CARD_CATEGORY, brand_id=brand_id,
                dedupe_key=f"decision:{decision_id}", message=_ESCALATED_MESSAGE,
            )
        return {"dedupe_key": dedupe_key, "outcome": "failed", "decision_id": decision_id,
                "error": error_text}

    decision_id = _write("auto_done", attempt_count, None)
    return {"dedupe_key": dedupe_key, "outcome": "auto_done", "decision_id": decision_id}


def run(conn, brand_id: str, *, actor: str, org_id: str) -> dict:
    """派工員：收集各登記模組的 status() 組 facts → decide() → 閘門 → 執行或出卡 → 寫
    decision 留痕。一個模組的 status() 壞了或缺席都不能讓整圈組不出 facts、更不能讓
    其他規則跟著卡住（拔根測試的程式版）。"""
    facts = {"brand_id": brand_id}
    for entry in MODULES.values():
        try:
            module_facts = entry["status"](conn, brand_id)
        except Exception:  # noqa: BLE001 — 一個模組的 status() 壞了不擋其他模組組 facts
            continue
        if module_facts:
            facts.update(module_facts)

    outcomes = [_process_action(conn, org_id, brand_id, action) for action in decide(facts)]
    conn.commit()
    return {"brand_id": brand_id, "actor": actor, "outcomes": outcomes}


# ---------------------------------------------------------------------------
# 刪品牌：向 app.core.cleanup 登記（同款登記見 app/core/campaign_skip.py 檔尾）。
# test_cleanup_coverage.py 會擋沒登記的帶 brand_id 新表。
# ---------------------------------------------------------------------------

BRAND_CASCADE_TABLES = (
    ("decision", "調度台決策留痕"),
)


def count_brand_data(conn, brand_id: str) -> list:
    counts = []
    for table, label in BRAND_CASCADE_TABLES:
        n = conn.execute(
            f"SELECT COUNT(*) AS c FROM {table} WHERE brand_id = %s", (brand_id,)
        ).fetchone()["c"]
        if n:
            counts.append((label, n))
    return counts


def delete_brand_data(conn, brand_id: str) -> dict:
    counts = dict(count_brand_data(conn, brand_id))
    for table, _label in BRAND_CASCADE_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE brand_id = %s", (brand_id,))
    return counts


cleanup.register("調度台決策留痕", count_brand=count_brand_data, delete_brand=delete_brand_data,
                 brand_tables={t for t, _ in BRAND_CASCADE_TABLES},
                 count_product=None, delete_product=None, product_tables=frozenset())
