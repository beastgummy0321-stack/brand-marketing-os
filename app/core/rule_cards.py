"""app/core/rule_cards.py — 規則卡通用機制（issue #12）。

「規則卡」＝可視可改的門檻數值：存資料庫（migration 附預設值種子）、有人話頁面可看可改可重設，
判定一律經這裡的純函數讀卡，不把數字寫死在判定邏輯裡（規則上限、規則過期、檔期日預算、
檔期方案數量上下限）。

新增一張規則卡：在 CARDS 常數加一筆定義（標題／說明／欄位），需要種子值再補一個遞增編號的
migration（本檔不擁有 SQL，schema 見 app/core/migrations/）。不用碰這支檔案其他部分。

沒被使用者改過的欄位，值就是 CARDS 裡的 default——DB 種子列雖然已經寫了同樣的數字，
但 `get_value` 兩邊都認得，表還沒建起來（極舊的 DB）也優雅回預設值，不噴錯。

分品牌（設定中心票 01）：每個品牌各自一份「系統預設值（CARDS 常數）→ 品牌覆寫值
（rule_card_value 表，PK 含 brand_id）」，`brand_id` 是本檔每個公開函式的必填參數，
不留「忘記傳＝悄悄套用平台預設」這種靜默跨品牌風險。A 品牌覆寫值不影響 B 品牌，
沒覆寫時繼續 fallback 到 CARDS 的 default（既有行為不變，只是查詢多一個過濾條件）。
"""

from __future__ import annotations

import psycopg

from app.core import cleanup
from app.core.audit import write_audit
from app.core.db import Conn, ConnProxy, now_utc

# ---------------------------------------------------------------------------
# 卡片定義（單一權威：標題、人話說明、欄位標籤與預設值都在這裡）
# ---------------------------------------------------------------------------

CARDS = {
    "rule_prompt_cap": {
        "title": "品牌智庫規則上限",
        "description": (
            "生成 prompt 會把這個品牌全部生效中的 hard 規則整包塞進去；soft 規則依最近確認"
            "時間排序，只取排在前面的部分——避免規則隨時間單調累積、prompt 被灌到失焦。"
            "超過上限而這次沒進 prompt 的規則不會消失，仍留在系統裡，只是這次生成用不到。"
            "數值來源：docs/adr/0012-rule-card-expiry-and-prompt-cap.md 第二、三節。"
        ),
        "fields": {
            "max_active_rules": {
                "label": "進生成提示詞的規則上限", "unit": "條", "default": 20.0,
                "help": "hard 規則不受這個數字限制、全部保留；soft 規則超過這個數字後，"
                        "排比較後面的那些這次不會進生成提示詞（不會被刪除，之後重新確認過"
                        "或排到前面就會恢復生效）。",
            },
        },
    },
    "schedule_budget": {
        "title": "檔期日預算",
        "description": (
            "檔期規劃出方案時，代理只給比例，這裡的日預算乘以比例才是真正花出去的金額——"
            "外殼算錢，代理不算錢（票 07）。預設 0 代表「使用者還沒填」，不是「預算是零」："
            "還沒填之前，排程一律拒絕，不會拿 0 去跑出一個沒有意義的方案。"
        ),
        "fields": {
            "daily_budget": {
                "label": "檔期日預算", "unit": "NT$", "default": 0.0,
                "help": "這期檔期每天要花多少預算。留 0 代表還沒設定，排程頁會先擋下來，"
                        "請先到這裡填一個數字再回去排程。",
            },
        },
    },
    "schedule_plan_count": {
        "title": "檔期方案數量上下限",
        "description": (
            "檔期規劃一次要代理出幾個方案，使用者從下拉選單挑一個數字——這張卡決定那個"
            "下拉選單的上下限，程式在送出前會擋掉超出範圍的數字，不是只在說明文字裡寫"
            "一個上限（票 08）。"
        ),
        "fields": {
            "plan_count_min": {
                "label": "方案數量下限", "unit": "個", "default": 1.0,
                "help": "一次最少出幾個方案。",
            },
            "plan_count_max": {
                "label": "方案數量上限", "unit": "個", "default": 5.0,
                "help": "一次最多出幾個方案——方案數愈多，代理輸出的 token 愈多，成本愈高。",
            },
        },
    },
}


def _field_def(card_key: str, field_key: str) -> dict:
    try:
        return CARDS[card_key]["fields"][field_key]
    except KeyError:
        raise ValueError(f"沒有這張規則卡欄位：{card_key}.{field_key}") from None


def get_value(conn: Conn | ConnProxy | None, brand_id: str, card_key: str, field_key: str) -> float:
    """讀一個門檻的目前值：這個品牌有存就用品牌覆寫值，沒有（或表還沒建起來）就用預設值。"""
    default = _field_def(card_key, field_key)["default"]
    if conn is None:
        return default
    try:
        row = conn.execute(
            "SELECT value FROM rule_card_value WHERE brand_id = %s AND card_key = %s AND field_key = %s",
            (brand_id, card_key, field_key),
        ).fetchone()
    except psycopg.Error:
        return default
    return row["value"] if row is not None else default


def get_card(conn: Conn | ConnProxy, brand_id: str, card_key: str) -> dict:
    """整張卡：標題、說明、每個欄位的定義與目前值（這個品牌的）——規則卡頁直接拿這個渲染。"""
    if card_key not in CARDS:
        raise ValueError(f"沒有這張規則卡：{card_key}")
    defn = CARDS[card_key]
    fields = [
        {"key": field_key, "value": get_value(conn, brand_id, card_key, field_key), **meta}
        for field_key, meta in defn["fields"].items()
    ]
    return {"key": card_key, "title": defn["title"], "description": defn["description"], "fields": fields}


def list_cards(conn: Conn | ConnProxy, brand_id: str) -> list:
    return [get_card(conn, brand_id, key) for key in CARDS]


def set_value(conn: Conn | ConnProxy, brand_id: str, card_key: str, field_key: str,
             value: float, actor: str, *, org_id: str) -> None:
    """改一個門檻值：落庫＋留稽核（brand_id 是真正的品牌事件，見 03 §3.1）。"""
    _field_def(card_key, field_key)  # 順便驗證卡／欄位存在
    before = get_value(conn, brand_id, card_key, field_key)
    conn.execute(
        """INSERT INTO rule_card_value (org_id, brand_id, card_key, field_key, value, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT(org_id, brand_id, card_key, field_key)
           DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
        (org_id, brand_id, card_key, field_key, value, now_utc()),
    )
    write_audit(
        conn, org_id=org_id, brand_id=brand_id, entity_type="rule_card_value",
        entity_id=f"{card_key}.{field_key}",
        action="update", actor=actor, before={"value": before}, after={"value": value},
    )
    conn.commit()


def reset_card(conn: Conn | ConnProxy, brand_id: str, card_key: str, actor: str, *,
               org_id: str) -> None:
    """整張卡重設回預設值。已經是預設值的欄位不重覆寫入、不留無意義的稽核紀錄。"""
    if card_key not in CARDS:
        raise ValueError(f"沒有這張規則卡：{card_key}")
    for field_key, meta in CARDS[card_key]["fields"].items():
        if get_value(conn, brand_id, card_key, field_key) != meta["default"]:
            set_value(conn, brand_id, card_key, field_key, meta["default"], actor, org_id=org_id)


# ---------------------------------------------------------------------------
# 品牌刪除清理登記（第 2 刀清理登記處，app.core.cleanup）：分品牌後 rule_card_value
# 帶了真正的 brand_id，刪品牌要跟著清掉品牌覆寫值，否則留下指向不存在品牌的孤兒列。
# ---------------------------------------------------------------------------

BRAND_CASCADE_TABLES = (
    ("rule_card_value", "規則卡覆寫值"),
)


def count_brand_data(conn, brand_id: str) -> list:
    """刪品牌前的清點，給刪除確認頁列出「按下去會消失什麼」。跟 delete_brand_data
    讀同一份 BRAND_CASCADE_TABLES——不各寫一份，避免清點與清除不同步。"""
    counts = []
    for table, label in BRAND_CASCADE_TABLES:
        n = conn.execute(
            f"SELECT COUNT(*) AS c FROM {table} WHERE brand_id = %s", (brand_id,)
        ).fetchone()["c"]
        if n:
            counts.append((label, n))
    return counts


def delete_brand_data(conn, brand_id: str) -> dict:
    """清掉本模組掛在該品牌下的資料，登記進 app.core.cleanup 給 delete_brand() 呼叫用。
    只下 DELETE、不 commit、不 rollback（commit 與 rollback 統一在
    brand_intelligence.delete_brand()）。"""
    counts = dict(count_brand_data(conn, brand_id))
    for table, _label in BRAND_CASCADE_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE brand_id = %s", (brand_id,))
    return counts


cleanup.register("規則卡覆寫值", count_brand=count_brand_data, delete_brand=delete_brand_data,
                 brand_tables={t for t, _ in BRAND_CASCADE_TABLES},
                 count_product=None, delete_product=None, product_tables=frozenset())
