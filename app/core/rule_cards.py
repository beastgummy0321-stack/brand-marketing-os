"""app/core/rule_cards.py — 規則卡通用機制（issue #12）。

「規則卡」＝可視可改的門檻數值：存資料庫（migration 附預設值種子）、有人話頁面可看可改可重設，
判定一律經這裡的純函數讀卡，不把數字寫死在判定邏輯裡（決策 0023 第 14、15、19、21 條都要用
這一套底座：帳戶結構門檻、預算配置門檻、樣本數速查表、素材疲勞門檻）。

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
    "budget_structure": {
        "title": "帳戶結構與預算配置門檻",
        "description": (
            "這張卡決定「日預算多少算小／中／大」，以及每個級距怎麼分帳戶結構與組別預算。"
            "小預算硬拆成兩組會讓每組都低於 Meta 的實務下限、兩組都跑不出數據，所以不硬拆；"
            "中預算用一個 CBO 活動分驗證與測試兩組；大預算開兩個獨立 CBO（放大＋測試），"
            "避免已驗證的贏家把新測試的預算全部吃光。方案生成與方案選擇頁都直接讀這裡的數字出底案。"
            "數值來源：app/methodology/ads-core.md 第 3 節。"
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
            "數值來源：app/methodology/ads-core.md 第 5 節。"
        ),
        "fields": {
            "cold_warning": {
                "label": "冷受眾開發 — 警示門檻", "unit": "頻率", "default": 2.5,
                "help": "冷受眾開發：安全 1.0–2.5，超過這個數字進入警示區（2.5–4.0）。",
            },
            "cold_danger": {
                # 業界危險分界 ~3.5（2026-08-08 體檢）
                "label": "冷受眾開發 — 危險門檻", "unit": "頻率", "default": 3.5,
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
    "rule_prompt_cap": {
        "title": "品牌智庫規則上限",
        "description": (
            "生成 prompt 會把這個品牌全部生效中的 hard 規則整包塞進去；soft 規則依最近確認"
            "時間排序，只取排在前面的部分——避免規則隨時間單調累積、prompt 被灌到失焦。"
            "超過上限而這次沒進 prompt 的規則不會消失，累積智慧頁會列出清單。"
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
    "rule_expiry": {
        "title": "規則有效期",
        "description": (
            "品牌智庫的規則被接受後，超過這裡設定的期數沒有人重新確認，狀態會自動退回"
            "「待確認」，不會再進生成 prompt——但規則本身不會被刪除，使用者到累積智慧頁"
            "一鍵「延續」即可恢復生效，不必重新輸入規則內容。一期抓檔期預設天數估算"
            "（app/ads/budget.py 的 DEFAULT_DURATION_DAYS，14 天）。"
            "數值來源：docs/adr/0012-rule-card-expiry-and-prompt-cap.md 第一節。"
        ),
        "fields": {
            "reconfirm_cycles": {
                "label": "重新確認門檻", "unit": "期", "default": 6.0,
                "help": "規則被接受（或上次重新確認）之後，經過這麼多期都沒有人重新確認過，"
                        "就會自動退回「待確認」狀態，暫時不會用在生成內容的判斷依據上。",
            },
        },
    },
    "pacing": {
        "title": "檔期預算步調門檻",
        "description": (
            "這張卡決定「檔期預算花得比時間進度快多少或慢多少」才算異常。判定拿兩個"
            "百分比相減：本期已經花掉的預算比例，減掉本期已經過去的時間比例。差距是正的"
            "且超過這個門檻＝燒太快（預算可能提前燒完）；差距是負的且超過門檻＝花不完"
            "（預算可能用不完）。門檻抓在合理範圍：太小容易把正常的花費波動誤報成異常，"
            "太大又會太晚才示警。檔期開跑不到 3 天不判定，樣本太少容易誤報（見"
            "app/ads/pacing.py）。"
        ),
        "fields": {
            "deviation_threshold_ratio": {
                "label": "步調偏差門檻", "unit": "比例（0–1）", "default": 0.15,
                "help": "花費進度與時間進度的差距超過這個比例（不分正負）就送出警示；"
                        "例如 0.15 代表兩邊差距超過 15 個百分點才算異常。",
            },
        },
    },
    "health_lights": {
        "title": "檔期健康燈號黃燈門檻",
        "description": (
            "這張卡決定燒錢速度／CPA／ROAS 三盞燈幾時轉黃：燒錢速度黃燈＝步調偏差門檻"
            "（pacing 卡）乘這裡的比例；CPA 黃燈＝目標 CPA 乘這裡的倍率，超過才轉黃、"
            "再超過這個倍率才轉紅；ROAS 黃燈＝打平投報率乘這裡的倍率，低於才轉黃、"
            "再低於這個倍率才轉紅。三盞燈各自的綠燈邊界不受這張卡影響（達到或優於"
            "目標／打平線就是綠燈），疲勞燈走既有 ad_creative_fatigue 卡，不在這裡。"
            "見 app/ads/health_lights.py。"
        ),
        "fields": {
            "spend_yellow_ratio": {
                "label": "燒錢速度黃燈比例", "unit": "比例（0–1）", "default": 0.6,
                "help": "花費進度與時間進度的差距超過步調門檻的這個比例，就轉黃燈提醒"
                        "留意；超過步調門檻本身則直接轉紅燈。",
            },
            "cpa_yellow_multiplier": {
                "label": "CPA 黃燈倍率", "unit": "倍", "default": 1.3,
                "help": "實際 CPA 超過目標 CPA、但沒超過目標乘這個倍率，算黃燈；"
                        "超過這個倍率才轉紅燈。",
            },
            "roas_yellow_multiplier": {
                "label": "ROAS 黃燈倍率", "unit": "倍", "default": 0.8,
                "help": "實際 ROAS 低於打平投報率、但沒低於打平投報率乘這個倍率，算黃燈；"
                        "低於這個倍率才轉紅燈。",
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
    "autonomy": {
        "title": "投放自動度",
        "description": (
            "決定這個品牌的廣告執行方式。保守檔會在提案與上線前等你核可，"
            "放手檔則在平台寫入 API 開通後，允許系統依煞車規則自動微調；"
            "兩種模式共用同一份執行清單。"
        ),
        "fields": {
            "mode": {
                "label": "執行模式", "unit": "檔", "default": 1.0,
                "help": "1.0＝保守檔（預設，提案與上線都等核可）；2.0＝放手檔（平台 API 開通後才會生效）。",
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
# 素材疲勞判定（示範卡的純函數消費端）
# ---------------------------------------------------------------------------

def classify_ad_frequency(conn: Conn, brand_id: str, audience_type: str,
                          frequency: float) -> str:
    """素材疲勞判定：純程式讀規則卡門檻比大小，回傳 'safe' / 'warning' / 'danger'。

    邊界對齊 app/methodology/ads-core.md 的寫法（例如冷受眾「警示 2.5–4.0」）：
    frequency 落在 [warning, danger] 算警示，超過 danger 才算危險。
    """
    if audience_type not in AUDIENCE_TYPE_LABELS:
        raise ValueError(f"不認得的受眾類型：{audience_type}")
    warning = get_value(conn, brand_id, "ad_creative_fatigue", f"{audience_type}_warning")
    danger = get_value(conn, brand_id, "ad_creative_fatigue", f"{audience_type}_danger")
    if frequency > danger:
        return "danger"
    if frequency >= warning:
        return "warning"
    return "safe"


# ---------------------------------------------------------------------------
# 樣本數統計等級（issue #18：把「錢的門檻」與「統計的門檻」分開）
# ---------------------------------------------------------------------------

def sample_size_tier(conn: Conn | None, brand_id: str,
                     sample_count: float | None, observed_rate: float | None) -> dict:
    """依樣本數速查表判斷這組數字算不算「統計等級」，回傳 'statistical' / 'directional'。

    沒有可比的轉換率（分母是 0，算不出比例）時，樣本數再多也無從查表比對——一律視為方向性判讀，
    不假裝有科學結論（決策 0023 第 19、20 點）。查表比對挑最接近觀察值的那一列基準轉換率。
    """
    if not observed_rate or not sample_count:
        return {"level": "directional", "required": None, "baseline": None}
    nearest = min(SAMPLE_SIZE_BASELINES, key=lambda b: abs(b - observed_rate))
    required = get_value(conn, brand_id, "sample_size", f"baseline_{round(nearest * 100)}pct")
    level = "statistical" if sample_count >= required else "directional"
    return {"level": level, "required": required, "baseline": nearest}


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
