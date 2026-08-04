# -*- coding: utf-8 -*-
"""app/core/rule_cards.py — 規則卡通用機制（issue #12）。

「規則卡」＝可視可改的門檻數值：存資料庫（migration 附預設值種子）、有人話頁面可看可改可重設，
判定一律經這裡的純函數讀卡，不把數字寫死在判定邏輯裡（決策 0023 第 14、15、19、21 條都要用
這一套底座：帳戶結構門檻、預算配置門檻、樣本數速查表、素材疲勞門檻）。

新增一張規則卡：在 CARDS 常數加一筆定義（標題／說明／欄位），需要種子值再補一個遞增編號的
migration（本檔不擁有 SQL，schema 見 app/core/migrations/）。不用碰這支檔案其他部分。

沒被使用者改過的欄位，值就是 CARDS 裡的 default——DB 種子列雖然已經寫了同樣的數字，
但 `get_value` 兩邊都認得，表還沒建起來（極舊的 DB）也優雅回預設值，不噴錯。
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from app.core.audit import write_audit
from app.core.db import now_iso

# ---------------------------------------------------------------------------
# 卡片定義（單一權威：標題、人話說明、欄位標籤與預設值都在這裡）
# ---------------------------------------------------------------------------

CARDS = {
    "budget_structure": {
        "title": "帳戶結構與預算配置門檻",
        "description": (
            "這張卡決定「日預算多少算小／中／大」，以及每個級距怎麼分帳戶結構與組別預算。"
            "小預算硬拆成兩組會讓每組都低於 Meta 的實務下限、兩組都跑不出數據，所以不硬拆；"
            "中預算用一個 CBO 活動分驗證與測試兩組；大預算開兩個獨立 CBO（放大＋測試），"
            "避免已驗證的贏家把新測試的預算全部吃光。方案生成與方案選擇頁都直接讀這裡的數字出底案。"
            "數值來源：app/methodology/ads.md 第 3 節。"
        ),
        "fields": {
            "min_daily_per_group": {
                "label": "每組日預算下限", "unit": "NT$", "default": 300.0,
                "help": "Meta 的實務下限：一組的日預算低於這個數字，一天拿不到足夠曝光，"
                        "跑完整期也很難累積出可判讀的數據。",
            },
            "medium_tier_floor": {
                "label": "中預算門檻（日預算達到此金額才分兩組）", "unit": "NT$", "default": 600.0,
                "help": "日預算低於這個數字算「小預算」——拆成兩組的話，每組都會低於上面的下限，"
                        "所以全額投入單一測試組，不硬拆。預設＝每組下限的兩倍。",
            },
            "large_tier_floor": {
                "label": "大預算門檻（日預算達到此金額才開雙活動）", "unit": "NT$", "default": 1200.0,
                "help": "日預算達到這個數字，才有本錢同時養「已驗證贏家放大」與「新概念測試」"
                        "兩個獨立活動，兩邊預算都還過得了下限。預設＝每組下限的四倍。",
            },
            "medium_validation_ratio": {
                "label": "中預算級距 — 已驗證方向佔比", "unit": "比例（0–1）", "default": 0.7,
                "help": "中預算用一個 CBO、兩個廣告組：這個比例留給比較有把握的方向，"
                        "剩下的留給新受眾／新素材測試。",
            },
            "large_scaling_ratio": {
                "label": "大預算級距 — 放大活動佔比", "unit": "比例（0–1）", "default": 0.8,
                "help": "大預算開兩個獨立 CBO 活動：放大活動（只放已驗證贏家）拿這個比例，"
                        "剩下的給測試活動（新概念與迭代版本），避免贏家把新測試餓死。",
            },
        },
    },
    "sample_size": {
        "title": "樣本數門檻（統計等級 vs 方向性判讀）",
        "description": (
            "這張卡決定「這期的樣本數夠不夠格說是統計上站得住腳的結論」，跟能不能繼續花錢的財務"
            "判斷是兩條分開的線（決策 0023 第 19、20 點）——毛利反推的打平／加碼／停損完全不受這張卡"
            "影響，就算樣本還沒到這裡的門檻，只要毛利算下來還能燒錢，仍可續投。這張卡只管「要宣布"
            "贏家或放大前，樣本夠不夠格」。數值取自 app/methodology/ab-testing.md 第 3 節樣本數速查表"
            "『要偵測 20% 提升幅度』那一欄（每個轉換率基準各查一次）——20% 是行銷實務最常抓的最小"
            "有意義效果；沒到門檻時，介面只會誠實顯示「方向性判讀」，不會假裝是嚴謹的統計結論。"
        ),
        "fields": {
            "baseline_1pct": {
                "label": "基準轉換率 1% 所需樣本數", "unit": "次／變體", "default": 97000.0,
                "help": "轉換率大約在 1% 上下時，要收到這麼多次點擊（或曝光，看比對哪個比例）"
                        "才夠格說是統計等級的結論。",
            },
            "baseline_3pct": {
                "label": "基準轉換率 3% 所需樣本數", "unit": "次／變體", "default": 31000.0,
                "help": "轉換率大約在 3% 上下時的樣本數門檻。",
            },
            "baseline_5pct": {
                "label": "基準轉換率 5% 所需樣本數", "unit": "次／變體", "default": 18000.0,
                "help": "轉換率大約在 5% 上下時的樣本數門檻。",
            },
            "baseline_10pct": {
                "label": "基準轉換率 10% 所需樣本數", "unit": "次／變體", "default": 8700.0,
                "help": "轉換率大約在 10% 上下時的樣本數門檻。",
            },
            "baseline_20pct": {
                "label": "基準轉換率 20% 所需樣本數", "unit": "次／變體", "default": 4000.0,
                "help": "轉換率大約在 20% 上下時的樣本數門檻。",
            },
        },
    },
    "ad_creative_fatigue": {
        "title": "素材疲勞頻率門檻",
        "description": (
            "「頻率」是同一個人平均看過這支素材幾次。看太多次會膩，成效跟著掉——"
            "這張卡決定頻率到多少算警示、到多少算危險。不同受眾類型能承受的頻率不一樣，"
            "門檻分開設。判讀與期中檢查都會直接讀這裡的數字，不會自己另外算。"
            "數值來源：app/methodology/ads.md 第 5 節。"
        ),
        "fields": {
            "cold_warning": {
                "label": "冷受眾開發 — 警示門檻", "unit": "頻率", "default": 2.5,
                "help": "冷受眾開發：安全 1.0–2.5，超過這個數字進入警示區（2.5–4.0）。",
            },
            "cold_danger": {
                "label": "冷受眾開發 — 危險門檻", "unit": "頻率", "default": 4.0,
                "help": "超過這個數字視為危險，代表這個概念已經耗盡，該考慮換素材或直接退場。",
            },
            "retargeting_warning": {
                "label": "再行銷 — 警示門檻", "unit": "頻率", "default": 4.0,
                "help": "再行銷受眾看到廣告的意願本來就比較高，容忍度也較高：安全 2.0–4.0。",
            },
            "retargeting_danger": {
                "label": "再行銷 — 危險門檻", "unit": "頻率", "default": 6.0,
                "help": "超過這個數字視為危險。",
            },
            "niche_warning": {
                "label": "小眾／精準受眾 — 警示門檻", "unit": "頻率", "default": 5.0,
                "help": "小眾受眾池子小，天然頻率就會偏高：安全 2.0–5.0。",
            },
            "niche_danger": {
                "label": "小眾／精準受眾 — 危險門檻", "unit": "頻率", "default": 8.0,
                "help": "超過這個數字視為危險。",
            },
        },
    },
}

# 素材疲勞判定要吃的受眾類型，人話標籤放這裡讓畫面與判定共用同一份詞彙。
AUDIENCE_TYPE_LABELS = {
    "cold": "冷受眾開發",
    "retargeting": "再行銷",
    "niche": "小眾／精準受眾",
}

FATIGUE_STATUS_LABELS = {
    "safe": "安全",
    "warning": "警示",
    "danger": "危險",
}

# 樣本數速查表的「基準轉換率」列（對應 CARDS["sample_size"] 的欄位命名 baseline_{1,3,5,10,20}pct）。
SAMPLE_SIZE_BASELINES = (0.01, 0.03, 0.05, 0.10, 0.20)

STATISTICAL_LEVEL_LABELS = {
    "statistical": "統計等級",
    "directional": "方向性判讀",
}


def _field_def(card_key: str, field_key: str) -> dict:
    try:
        return CARDS[card_key]["fields"][field_key]
    except KeyError:
        raise ValueError(f"沒有這張規則卡欄位：{card_key}.{field_key}") from None


def get_value(conn: Optional[sqlite3.Connection], card_key: str, field_key: str) -> float:
    """讀一個門檻的目前值：DB 有存就用 DB 的，沒有（或表還沒建起來）就用預設值。"""
    default = _field_def(card_key, field_key)["default"]
    if conn is None:
        return default
    try:
        row = conn.execute(
            "SELECT value FROM rule_card_value WHERE card_key = ? AND field_key = ?",
            (card_key, field_key),
        ).fetchone()
    except sqlite3.OperationalError:
        return default
    return row["value"] if row is not None else default


def get_card(conn: sqlite3.Connection, card_key: str) -> dict:
    """整張卡：標題、說明、每個欄位的定義與目前值——規則卡頁直接拿這個渲染。"""
    if card_key not in CARDS:
        raise ValueError(f"沒有這張規則卡：{card_key}")
    defn = CARDS[card_key]
    fields = [
        {"key": field_key, "value": get_value(conn, card_key, field_key), **meta}
        for field_key, meta in defn["fields"].items()
    ]
    return {"key": card_key, "title": defn["title"], "description": defn["description"], "fields": fields}


def list_cards(conn: sqlite3.Connection) -> list:
    return [get_card(conn, key) for key in CARDS]


def set_value(conn: sqlite3.Connection, card_key: str, field_key: str, value: float, actor: str) -> None:
    """改一個門檻值：落庫＋留稽核（brand_id=None，這是平台層級設定，不是品牌資料）。"""
    _field_def(card_key, field_key)  # 順便驗證卡／欄位存在
    before = get_value(conn, card_key, field_key)
    conn.execute(
        """INSERT INTO rule_card_value (card_key, field_key, value, updated_at) VALUES (?, ?, ?, ?)
           ON CONFLICT(card_key, field_key)
           DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
        (card_key, field_key, value, now_iso()),
    )
    write_audit(
        conn, brand_id=None, entity_type="rule_card_value", entity_id=f"{card_key}.{field_key}",
        action="update", actor=actor, before={"value": before}, after={"value": value},
    )
    conn.commit()


def reset_card(conn: sqlite3.Connection, card_key: str, actor: str) -> None:
    """整張卡重設回預設值。已經是預設值的欄位不重覆寫入、不留無意義的稽核紀錄。"""
    if card_key not in CARDS:
        raise ValueError(f"沒有這張規則卡：{card_key}")
    for field_key, meta in CARDS[card_key]["fields"].items():
        if get_value(conn, card_key, field_key) != meta["default"]:
            set_value(conn, card_key, field_key, meta["default"], actor)


# ---------------------------------------------------------------------------
# 素材疲勞判定（示範卡的純函數消費端）
# ---------------------------------------------------------------------------

def classify_ad_frequency(conn: sqlite3.Connection, audience_type: str, frequency: float) -> str:
    """素材疲勞判定：純程式讀規則卡門檻比大小，回傳 'safe' / 'warning' / 'danger'。

    邊界對齊 app/methodology/ads.md 的寫法（例如冷受眾「警示 2.5–4.0」）：
    frequency 落在 [warning, danger] 算警示，超過 danger 才算危險。
    """
    if audience_type not in AUDIENCE_TYPE_LABELS:
        raise ValueError(f"不認得的受眾類型：{audience_type}")
    warning = get_value(conn, "ad_creative_fatigue", f"{audience_type}_warning")
    danger = get_value(conn, "ad_creative_fatigue", f"{audience_type}_danger")
    if frequency > danger:
        return "danger"
    if frequency >= warning:
        return "warning"
    return "safe"


# ---------------------------------------------------------------------------
# 樣本數統計等級（issue #18：把「錢的門檻」與「統計的門檻」分開）
# ---------------------------------------------------------------------------

def sample_size_tier(conn: Optional[sqlite3.Connection], sample_count: Optional[float],
                     observed_rate: Optional[float]) -> dict:
    """依樣本數速查表判斷這組數字算不算「統計等級」，回傳 'statistical' / 'directional'。

    沒有可比的轉換率（分母是 0，算不出比例）時，樣本數再多也無從查表比對——一律視為方向性判讀，
    不假裝有科學結論（決策 0023 第 19、20 點）。查表比對挑最接近觀察值的那一列基準轉換率。
    """
    if not observed_rate or not sample_count:
        return {"level": "directional", "required": None, "baseline": None}
    nearest = min(SAMPLE_SIZE_BASELINES, key=lambda b: abs(b - observed_rate))
    required = get_value(conn, "sample_size", f"baseline_{round(nearest * 100)}pct")
    level = "statistical" if sample_count >= required else "directional"
    return {"level": level, "required": required, "baseline": nearest}
