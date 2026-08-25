# -*- coding: utf-8 -*-
"""app/ads/plan.py — 本期廣告計畫的多方案生成（票 4，決策 0023 第 1、13 點）。

比照 app/brand_intelligence/report.py 的做法：context_compiler 組出已確認事實／規則／宣稱，
交給模型產出本期打法，回覆逐字保留、程式只驗形狀不改寫（鐵則 2）。

分工（決策 0016 硬性原則 4）：
- 語言與創意（受眾描述、切角、訊息）走 LLM。
- 數字（預算、期長、分配）與受眾三層的「可用性」一律不進 prompt 要求模型算——已由程式算好
  （budget.py／audience_availability()），這裡只是把結果**告訴**模型，模型只能在可用的層
  裡寫描述，不能自己判定某層能不能打。

R3-carry-forward-winners（B0-29／B0-36）：上期真正打贏的切角（`carry_forward.prior_winners()`）
與已驗證賠錢的方向（`carry_forward.rejected_directions()`）都是程式從歷史成效資料算好、
具名帶進 prompt，不是丟一句抽象的 learning_ledger 文字讓模型自己猜「有效方向」是什麼。

## 兩步流程（票 4 之前是一步）

1. `generate_options()`：一次生成 2–4 個完整方案（其中一個標 AI 推薦），存進暫存表
   `campaign_plan_option`（見該表 migration 的說明：暫存工作表，不是事實層）。
   檔期狀態轉成 PLAN_SELECT（等老闆選）。
2. `select_option()`：老闆選定一個（或用自訂方向重新跑一輪 generate_options 再選），
   選定的那個才落地成 campaign_plan 的新版本（沿用既有 append-only 版本機制），
   檔期狀態轉成 REVIEW，之後走既有的關卡一 `approve()`，行為不變。

資料不足照樣生成（決策 0013），只是要求模型把推測寫成推測。
生成失敗一律回 (False, 人話錯誤)，不入庫半份方案。
"""

import json
from typing import Callable, Optional

from app.ads import account_structure
from app.ads import carry_forward
from app.ads import handoff as ads_handoff
from app.ads import opening_suggestion
from app.ads import plan_citation
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi
from app.core import settings as coresettings
from app.core.audit import write_audit
from app.core.db import new_id, now_iso
from app.llm import context_compiler, gateway, methodology, pricing, providers

PROVIDER = providers.AnthropicProvider()  # 測試整包換掉

DEFAULT_ANGLE_COUNT = 4  # 切角數量為可設定值，不寫死在 prompt（build.md §26）
DEFAULT_OPTION_COUNT = 3  # 方案數量，決策 0023 第 1 點：2–4 個
MIN_OPTION_COUNT = 2
MAX_OPTION_COUNT = 4
PLAN_MAX_TOKENS = 24000  # 也是花費上限攔截（票 M2）的呼叫前保守估計依據，見 generate_options()

# 對應 app/methodology/README.md 對照表的列名（票 11）；改對照表內容不必改這裡。
METHODOLOGY_TASK_LABELS = ["檔期計畫生成"]

PARSE_FAIL_MESSAGE = "AI 有回覆，但格式讀不成預期的樣子。可以再試一次。"

OBJECTIVE_TEXT = {
    "awareness": "讓更多人認識這個品牌",
    "traffic": "把人導去網站或某個頁面",
    "engagement": "累積留言、分享、按讚等互動",
    "leads": "收集潛在客戶名單",
    "sales": "直接帶來訂單",
}

# 漏斗階段：由「本期目標」推導，不是使用者另外填的欄位（使用者 2026-08-06 grill 第 4 題，
# 票 04-wire-funnel-stage）。這是唯一一份對照表——判讀依漏斗層換尺（後續票）與畫面顯示
# 都查這裡，不得另外抄一份。
FUNNEL_STAGE_LABELS = {
    "exposure": "曝光層",
    "consideration": "考慮層",
    "conversion": "轉換層",
}

OBJECTIVE_TO_FUNNEL_STAGE = {
    "awareness": "exposure",
    "traffic": "consideration",
    "engagement": "consideration",
    "leads": "conversion",
    "sales": "conversion",
}


def derive_funnel_stage(objective: str) -> Optional[str]:
    """本期目標推導出的漏斗階段。objective 不在對照表裡（理論上不會發生，開期表單已驗證
    只能是 OBJECTIVE_TEXT 的五個值之一）時老實回 None，不瞎猜（鐵則 16）。"""
    return OBJECTIVE_TO_FUNNEL_STAGE.get(objective)

# 受眾三層（決策 0023 第 13 點）：順序＝人話理解順序（陌生 → 認識 → 買過），
# 頁面與 prompt 共用同一份順序與標籤，不各自維護一份。
AUDIENCE_TIERS = ["cold", "warm", "hot"]
AUDIENCE_TIER_LABELS = {
    "cold": "冷受眾（陌生開發）",
    "warm": "暖受眾（再行銷）",
    "hot": "熱受眾（已成交／高互動）",
}

# 具名異議（票 5，決策 0023 第 14、15、18(b) 點）：AI 只能對這三種底案講意見，不能改數字。
DISSENT_TARGETS = ("account_structure", "budget_allocation", "offer")
DISSENT_TARGET_LABELS = {
    "account_structure": "帳戶結構",
    "budget_allocation": "預算配置",
    "offer": "這期的 Offer",
}
MAX_DISSENT_COUNT = 3

_SYSTEM = (
    "你是資深廣告投手，正在替客戶規劃一期 Meta 廣告的打法。"
    "只回傳 JSON，不要任何 JSON 以外的文字。全部用繁體中文。"
)


# ---------------------------------------------------------------------------
# 受眾三層可用性（程式算好的事實，不問模型；決策 0016 硬性原則 4）
# ---------------------------------------------------------------------------

def audience_availability(conn, brand_id: str) -> dict:
    """三層受眾這期各自能不能用。

    冷受眾（陌生開發）永遠可用；暖層要有過站內流量才有再行銷池、熱層要有過成交才有
    高意向名單——用這個品牌歷史上所有未被隔離的成效快照（跨檔期累積，因為受眾資產是
    品牌層級慢慢累積的，不是單一檔期的事）判斷，不是問模型「這期能不能打暖受眾」。
    """
    row = conn.execute(
        "SELECT COALESCE(SUM(clicks), 0) c, COALESCE(SUM(conversions), 0) v"
        " FROM performance_snapshot WHERE brand_id = ? AND quarantined = 0",
        (brand_id,),
    ).fetchone()
    has_traffic = (row["c"] or 0) > 0
    has_conversions = (row["v"] or 0) > 0
    return {
        "cold": {
            "available": True,
            "reason": "陌生開發受眾不需要任何既有資產，永遠可以打。",
        },
        "warm": (
            {"available": True,
             "reason": "已經有廣告帶來過網站流量，可以對這些人做再行銷。"}
            if has_traffic else
            {"available": False,
             "reason": "還沒有廣告帶來過網站流量，沒有再行銷受眾池，這期打不了暖受眾。"}
        ),
        "hot": (
            {"available": True,
             "reason": "已經有成交紀錄，可以針對這些人做熱受眾（回購／同類推薦）。"}
            if has_conversions else
            {"available": False,
             "reason": "還沒有成交紀錄，沒有名單可以拿來做回購或相似受眾，這期打不了熱受眾。"}
        ),
    }


def audience_summary_text(audience: dict) -> str:
    """三層受眾摘成一句人話文字——給只吃字串的欄位用（例如 experiment_cell.audience）。"""
    tiers = audience.get("tiers", {}) if isinstance(audience, dict) else {}
    parts = [
        f"{AUDIENCE_TIER_LABELS[tier]}：{tiers[tier]['description']}"
        for tier in AUDIENCE_TIERS
        if tiers.get(tier, {}).get("available") and tiers[tier].get("description")
    ]
    return "；".join(parts) if parts else "（這期沒有標出受眾說明）"


# ---------------------------------------------------------------------------
# 驗形（票 4 起：一次驗多個方案，每個方案的形狀跟舊版單一計畫一樣，多了 audience 結構與
# is_recommended／difference 兩個欄位）
# ---------------------------------------------------------------------------

def _normalize_angles(raw, angle_count: int) -> list:
    angles = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        title, message = item.get("title"), item.get("message")
        if not isinstance(title, str) or not title.strip():
            continue
        if not isinstance(message, str) or not message.strip():
            continue
        angles.append({
            "title": title.strip(),
            "message": message.strip(),
            "why": (item.get("why") or "").strip() if isinstance(item.get("why"), str) else "",
            "product_id": item.get("product_id") if isinstance(item.get("product_id"), str) else None,
        })
    return angles[:angle_count]


def _normalize_hypotheses(raw) -> list:
    hypotheses = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        statement = item.get("statement")
        if not isinstance(statement, str) or not statement.strip():
            continue
        kind = item.get("type")
        hypotheses.append({
            "type": kind if kind in ("audience", "message") else "message",
            "statement": statement.strip(),
            "verify": (item.get("verify") or "").strip() if isinstance(item.get("verify"), str) else "",
        })
    return hypotheses[:4]


def _normalize_grounding(raw) -> dict:
    grounding = {"facts": [], "inferences": [], "to_verify": []}
    if isinstance(raw, dict):
        for key in grounding:
            values = raw.get(key)
            if isinstance(values, list):
                grounding[key] = [v.strip() for v in values
                                  if isinstance(v, str) and v.strip()][:8]
    return grounding


def _normalize_audience(raw, availability: dict) -> dict:
    """可用性與理由一律用程式算好的事實覆蓋（不信任模型的判定），描述才是模型寫的。"""
    raw = raw if isinstance(raw, dict) else {}
    tiers = {}
    for tier, facts in availability.items():
        entry = raw.get(tier) if isinstance(raw.get(tier), dict) else {}
        description = entry.get("description")
        description = description.strip() if isinstance(description, str) else ""
        tiers[tier] = {
            "available": facts["available"],
            "reason": facts["reason"],
            "description": description if facts["available"] else "",
        }
    exclusions = [e.strip() for e in (raw.get("exclusions") or [])
                  if isinstance(e, str) and e.strip()][:6]
    return {"tiers": tiers, "exclusions": exclusions}


def _normalize_option(data, angle_count: int, availability: dict) -> Optional[dict]:
    if not isinstance(data, dict):
        return None
    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return None

    audience = _normalize_audience(data.get("audience"), availability)
    if not audience["tiers"]["cold"]["description"]:
        return None  # 冷受眾永遠可用，連這層都沒寫描述＝這個方案內容太空洞

    angles = _normalize_angles(data.get("angles"), angle_count)
    if not angles:
        return None

    return {
        "summary": summary.strip(),
        "difference": (data.get("difference") or "").strip()
        if isinstance(data.get("difference"), str) else "",
        "audience": audience,
        "angles": angles,
        "hypotheses": _normalize_hypotheses(data.get("hypotheses")),
        "grounding": _normalize_grounding(data.get("grounding")),
        "is_recommended": bool(data.get("is_recommended")),
    }


def _normalize_options(data, angle_count: int, availability: dict) -> Optional[list]:
    """回傳 2–4 個有效方案，剛好一個 is_recommended=True；不足 2 個算失敗（None）。"""
    if not isinstance(data, dict) or not isinstance(data.get("options"), list):
        return None

    options = []
    for item in data["options"]:
        option = _normalize_option(item, angle_count, availability)
        if option is not None:
            options.append(option)
        if len(options) >= MAX_OPTION_COUNT:
            break

    if len(options) < MIN_OPTION_COUNT:
        return None

    recommended = [o for o in options if o["is_recommended"]]
    if len(recommended) != 1:
        for index, option in enumerate(options):
            option["is_recommended"] = (index == 0)
    return options


def _normalize_dissents(raw) -> list:
    """具名異議：只認得三種 target、必附建議與理由，超過上限截斷。不是清單就當沒有意見。"""
    dissents = []
    if not isinstance(raw, list):
        return dissents
    for item in raw:
        if not isinstance(item, dict):
            continue
        target = item.get("target")
        suggestion = item.get("suggestion")
        reason = item.get("reason")
        if target not in DISSENT_TARGETS:
            continue
        if not isinstance(suggestion, str) or not suggestion.strip():
            continue
        if not isinstance(reason, str) or not reason.strip():
            continue
        dissents.append({"target_type": target, "suggestion": suggestion.strip(),
                         "reason": reason.strip()})
        if len(dissents) >= MAX_DISSENT_COUNT:
            break
    return dissents


# ---------------------------------------------------------------------------
# 帳戶結構＋預算配置底案（票 5）：純程式算好告訴模型，模型不能自己改數字，只能具名異議。
# ---------------------------------------------------------------------------

def _structure_baseline_text(structure: account_structure.StructureRecommendation) -> str:
    lines = [f"帳戶結構：{structure.structure_label}（{structure.tier_label}）", structure.note]
    for g in structure.groups:
        floor_note = "（低於 Meta 每組日預算下限，可能跑不出可判讀數據）" if g.below_floor else ""
        lines.append(f"- {g.label}：約 {g.ratio:.0%}，日預算約 {g.daily_budget:,.0f} 元{floor_note}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompt 組裝
# ---------------------------------------------------------------------------

def _is_carry_forward_cycle(cycle: dict) -> bool:
    """這期是不是真的走「沿用有效方向」（R3-carry-forward-winners，B0-29／B0-36 修法）。

    使用者的二選一（`NewCycleDirectionChoice.tsx`）不是存在某個獨立的 mode 欄位——按下
    「沿用有效方向」時，前端把 `f"{CARRY_FORWARD_DIRECTION}：{direction}"` 逐字塞進
    `background` 欄位送給 `createCycle`（`OpeningSuggestionCard.tsx`），這是全系統唯一
    留下來、可回頭讀到的「使用者選了沿用」信號；按「推新品／換方向」時 `background` 是
    空字串（存進 DB 變 `None`，見 `repository.py:create_cycle()`），使用者自己輸入的
    自訂方向則是任意文字，兩者都不該觸發「延續上期切角」的 prompt 段落——一個是使用者
    明講要換方向，一個是使用者自己已經講了要打什麼，都不該讓程式硬塞一段「不要換切角」
    的指示跟使用者的意思對著幹。
    """
    background = cycle.get("background") or ""
    return background.startswith(f"{opening_suggestion.CARRY_FORWARD_DIRECTION}：")


def _build_options_user_text(brand: dict, cycle: dict, allocations: list, context_text: str,
                             methodology_text: str, angle_count: int, fact_count: int,
                             availability: dict, option_count: int,
                             custom_direction: Optional[str],
                             structure: account_structure.StructureRecommendation,
                             prior_winners: list, avoid_directions: list) -> str:
    plan = ads_repo.derived_plan(cycle)
    parts = [
        f"品牌名稱：{brand['name']}",
        f"本期目標：{OBJECTIVE_TEXT.get(cycle['objective'], cycle['objective'])}",
        f"檔期：{cycle['start_date']} 到 {cycle['end_date']}（共 {plan.get('duration_days')} 天）",
        f"總預算：{cycle['budget']:,.0f} {cycle['currency']}，"
        f"平均每天約 {plan.get('daily_budget', 0):,.0f}",
        "投放平台：Meta（Facebook／Instagram）",
    ]
    if cycle.get("background"):
        parts.append(f"這期背景（老闆填的，出方案前務必先讀）：{cycle['background']}")

    if allocations:
        lines = "\n".join(
            f"- {a['product_name']}：分配 {a['allocated_budget']:,.0f}"
            + ("（這個產品還沒有成本售價資料，分配只是估的）" if a["economics_missing"] else "")
            for a in allocations
        )
        parts.append("這期要推的產品與各自預算：\n" + lines)
    else:
        parts.append("這期以整個品牌為範圍，沒有指定個別產品。")

    parts.append(context_text if context_text
                 else "（目前沒有任何已確認的品牌資料。）")

    if methodology_text:
        parts.append("【方法論】規劃本期打法時請依循以下專業行銷準則：\n" + methodology_text)

    avail_lines = "\n".join(
        f"- {AUDIENCE_TIER_LABELS[tier]}：{'可用' if availability[tier]['available'] else '這期不能用'}"
        f"（{availability[tier]['reason']}）"
        for tier in AUDIENCE_TIERS
    )
    parts.append(
        "三層受眾的可用性是已經確認的事實，你不能改判、不能假裝可用層以外的層能打：\n"
        + avail_lines
    )

    parts.append(
        "帳戶結構與預算配置底案（程式依規則卡算好，你不能改動這些數字，只能講意見）：\n"
        + _structure_baseline_text(structure)
    )

    if prior_winners:
        lines = "\n".join(
            f"- {w['angle']}：ROAS {w['roas']}，花費 NT${w['spend']:,.0f}，"
            f"轉換 {w['conversions']:.0f} 次（來源期別 {w['source_cycle_id']}，"
            "這一個也要在推薦案裡出現，並寫出這個數字）"
            for w in prior_winners
        )
        parts.append(
            "上期以來真正打出成績的切角（這才是「沿用有效方向」該沿用的東西——"
            "不要整批換成沒出現過的新切角）：\n" + lines
        )

    if avoid_directions:
        lines = "\n".join(
            f"- {a['statement']}（上期此方向賠錢，已避開；來源期別 {a['source_cycle_id']}）"
            for a in avoid_directions
        )
        parts.append("已驗證賠錢、這期不要再選的方向：\n" + lines)

    if custom_direction and custom_direction.strip():
        parts.append(f"老闆對這批方案的額外指示（務必照這個方向調整，不要忽略）：{custom_direction.strip()}")

    product_hint = ("每個產品至少要有一個切角。" if len(allocations) > 1 else "")
    hard_rules = [
        "預算、天數、分配金額都已經算好了（上面那些數字），你不要重算也不要改，"
        "需要提到時直接引用，每個方案共用同一組數字。",
        "不得放寬或新增可用宣稱——只能用上面已登錄的宣稱，硬性限制規則一律遵守。",
        "依據來自已確認事實的內容放進 grounding.facts；你自己的推論放 inferences；"
        "需要靠這期投放才能驗證的放 to_verify。三者不要混在一起。",
        "不要編造市佔率、營收、檢驗數據或競品名稱。",
        "受眾只能在標「可用」的層裡寫描述；不可用的層留空字串，不要硬掰。",
        "每個方案都要用 difference 講清楚它跟其他方案的差別在哪，不要寫得看起來都一樣。",
    ]
    if prior_winners:
        # 票 F15：這條指示搬到硬規則清單裡（原本只在贏家段落下面的一句話，模型讀不到）。
        hard_rules.append(
            "你推薦的那個方案（is_recommended: true）裡，上面每一個贏家都要逐一點名、"
            "並且原樣寫出它的 ROAS 數字；真的不打算沿用某一個，也要在方案裡講清楚原因。"
        )
    rule_count_cn = {6: "六", 7: "七"}[len(hard_rules)]
    rules_text = "\n".join(f"{i}. {rule}" for i, rule in enumerate(hard_rules, start=1))
    parts.append(
        f"請規劃本期打法，一次產出 {option_count} 個策略方向真的不一樣的方案（不要只是換句話說），"
        "其中剛好一個要標成 AI 推薦（is_recommended: true，其餘為 false）。"
        f"每個方案都要各自完整，各自有 {angle_count} 個創意切角。{product_hint}\n"
        f"{rule_count_cn}條硬規則：\n" + rules_text
    )

    if fact_count < 5:
        parts.append(
            f"這個品牌目前只有 {fact_count} 條已確認資料，請照樣完成規劃，"
            "但把推測明白寫成推測，不要編造具體數字。"
        )

    parts.append(
        "具名異議（選填，最多 3 條）：如果你讀完這期背景，對上面的帳戶結構或預算配置底案"
        "有具體、有理由的不同意見，可以在 dissents 陣列提出建議——只能講方向與理由，"
        "不能自己改數字（target: \"account_structure\" 或 \"budget_allocation\"）。"
        "另外，如果你看到這個品牌目前明顯只有「純產品＋價格」、沒有任何保證或值得信任的理由，"
        "也用同一個陣列提醒一句（target: \"offer\"）。沒有意見就給空陣列，不要為了湊數硬找理由，"
        "這件事不會擋流程、不影響你出的方案。"
    )

    parts.append(
        "輸出格式：只回傳以下 JSON：\n"
        '{\n'
        '  "dissents": [{"target": "account_structure/budget_allocation/offer 三選一",'
        ' "suggestion": "你的建議，只能講方向不能給數字", "reason": "為什麼"}],\n'
        '  "options": [\n'
        '    {\n'
        '      "is_recommended": true 或 false,\n'
        '      "summary": "這個方案打法的一句話總結",\n'
        '      "difference": "這個方案跟其他方案的差別在哪，一句話",\n'
        '      "audience": {\n'
        '        "cold": {"description": "冷受眾要打誰、怎麼描述"},\n'
        '        "warm": {"description": "暖受眾要打誰（這層不可用時留空字串）"},\n'
        '        "hot": {"description": "熱受眾要打誰（這層不可用時留空字串）"},\n'
        '        "exclusions": ["這個方案要排除的對象"]\n'
        '      },\n'
        '      "angles": [{"title": "切角名稱", "message": "這個切角要傳達什麼",'
        ' "why": "為什麼這個切角值得試", "product_id": "對應的產品 id 或 null"}],\n'
        '      "hypotheses": [{"type": "audience 或 message", "statement": "這期想驗證的假設",'
        ' "verify": "看什麼數字算驗證成功"}],\n'
        '      "grounding": {"facts": ["依據的已確認事實"], "inferences": ["AI 的推論"],'
        ' "to_verify": ["還沒驗證的假設"]}\n'
        '    }\n'
        '  ]\n'
        '}'
    )
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# 生成方案（第一步）
# ---------------------------------------------------------------------------

def generate_options(conn, brand_id: str, cycle_id: str, actor: str, *,
                     angle_count: int = DEFAULT_ANGLE_COUNT,
                     option_count: int = DEFAULT_OPTION_COUNT,
                     custom_direction: Optional[str] = None,
                     include_methodology: bool = True,
                     on_stage: Optional[Callable[[str], None]] = None) -> tuple:
    """生成本期的 2–4 個方案並存成暫存批次。成功回 (True, None)；失敗回 (False, 人話錯誤)。

    include_methodology=False（票 11 效果盲測專用）：略過方法論載入，其餘上下文與流程
    完全相同，讓「接線前」對照組真的跑同一條生產管線，不是另外寫一份平行邏輯。

    on_stage（票 29，等待頁誠實化）：每進到下一個實際階段就回報一次階段代碼
    （"ask_ai"／"save"），呼叫端（app/ads/routes.py）拿來更新等待頁的階段清單；
    不傳就是沒有等待頁在追蹤，純函式呼叫（既有測試）行為不變。
    """
    brand = bi.get_brand(conn, brand_id)
    if brand is None:
        raise ValueError(f"找不到品牌：{brand_id}")
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if cycle is None:
        raise ValueError(f"找不到廣告檔期：{cycle_id}")

    # 花費上限攔截（票 M2）：跟品牌智庫的產品調研共用同一道上限與同一個檢查函式，呼叫前先擋，
    # 沒有真實用量校準資料可用時改用 pricing.cost_ceiling() 抓一個不會低估的保守天花板。
    model = providers.resolve_model(task_type="campaign_plan", conn=conn)
    budget_err = coresettings.budget_exceeded_message(
        conn, brand_id, pricing.cost_ceiling(model, PLAN_MAX_TOKENS),
        action="這期的計畫生成",
        fallback_hint="可以先選用已經產出的方案，或到設定頁調高上限後再試。")
    if budget_err:
        return False, budget_err

    allocations = ads_repo.list_cycle_products(conn, brand_id, cycle_id)
    context_text, knowledge_item_ids, brand_version, _ = context_compiler.compile(conn, brand_id)
    product_ids = {a["product_id"] for a in allocations}
    is_carry_forward = _is_carry_forward_cycle(cycle)
    prior_winners = (carry_forward.prior_winners(conn, brand_id, product_ids=product_ids,
                                                 exclude_cycle_id=cycle_id)
                     if is_carry_forward else [])
    avoid_directions = (carry_forward.rejected_directions(conn, brand_id, product_ids=product_ids)
                       if is_carry_forward else [])
    methodology_result = (
        methodology.compile(conn, METHODOLOGY_TASK_LABELS, brand_id=brand_id, actor=actor)
        if include_methodology
        else methodology.MethodologyResult(text="", missing_files=[], loaded_files=[])
    )
    availability = audience_availability(conn, brand_id)
    angle_count = max(angle_count, len(allocations))
    option_count = max(MIN_OPTION_COUNT, min(option_count, MAX_OPTION_COUNT))
    structure = account_structure.recommend(conn, brand_id, ads_repo.derived_plan(cycle)["daily_budget"])

    user_text = _build_options_user_text(
        brand, cycle, allocations, context_text, methodology_result.text, angle_count,
        len(knowledge_item_ids), availability, option_count, custom_direction, structure,
        prior_winners, avoid_directions)

    if on_stage:
        on_stage("ask_ai")
    task = gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type="campaign_plan",
        prompt_template_id="campaign_plan_options", prompt_template_version="v1",
        system=_SYSTEM, messages=[{"role": "user", "content": user_text}],
        context=gateway.TaskContext(
            context_scope={"brand_id": brand_id, "campaign_cycle_id": cycle_id,
                           # 這次真的組進 prompt 的方法論檔，事後回推不出來（ADR 0009）
                           "methodology_files": methodology_result.loaded_files},
            knowledge_item_ids=knowledge_item_ids, brand_version=brand_version,
        ),
        # 開網路搜尋（ADR 0005）：出方案要知道當下的檔期與市場氛圍，讓 AI 自己去查。
        options=gateway.TaskOptions(max_tokens=PLAN_MAX_TOKENS,
                                    tools=[providers.WEB_SEARCH_TOOL]),
    )
    if task["status"] != "succeeded":
        return False, task["error"]
    if on_stage:
        on_stage("save")

    parsed = gateway.parse_json_reply(task["rendered_output"])
    options = _normalize_options(parsed, angle_count, availability)
    if options is None:
        return False, PARSE_FAIL_MESSAGE
    violations = plan_citation.citation_violations(options, prior_winners, avoid_directions)
    if violations:
        return False, plan_citation.citation_error_message(violations)
    dissents = _normalize_dissents((parsed or {}).get("dissents"))

    _persist_options(conn, brand_id, cycle_id, options, task["id"],
                     methodology_result.missing_files, actor)
    ads_repo.replace_pending_dissents(conn, brand_id, cycle_id, dissents, task["id"])
    return True, None


def _persist_options(conn, brand_id: str, cycle_id: str, options: list, llm_task_id: str,
                     methodology_missing: list, actor: str) -> None:
    ts = now_iso()
    conn.execute(
        "DELETE FROM campaign_plan_option WHERE brand_id = ? AND campaign_cycle_id = ?",
        (brand_id, cycle_id),
    )
    for index, option in enumerate(options):
        payload = dict(option)
        payload["llm_task_id"] = llm_task_id
        payload["methodology_missing"] = methodology_missing
        conn.execute(
            "INSERT INTO campaign_plan_option (id, campaign_cycle_id, brand_id, option_index,"
            " is_recommended, option_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (new_id("cpo"), cycle_id, brand_id, index, int(option["is_recommended"]),
             json.dumps(payload, ensure_ascii=False), ts),
        )
    ads_repo.update_cycle_status(conn, brand_id, cycle_id, status="PLAN_SELECT", actor=actor)


def get_pending_options(conn, brand_id: str, cycle_id: str) -> list:
    """這一批還沒被選定的方案，依 AI 出的順序排列。"""
    rows = conn.execute(
        "SELECT * FROM campaign_plan_option WHERE brand_id = ? AND campaign_cycle_id = ?"
        " ORDER BY option_index",
        (brand_id, cycle_id),
    ).fetchall()
    options = []
    for row in rows:
        option = json.loads(row["option_json"])
        option["id"] = row["id"]
        option["is_recommended"] = bool(row["is_recommended"])
        options.append(option)
    return options


# ---------------------------------------------------------------------------
# 選定方案（第二步）：落地成正式計畫，沿用既有版本機制
# ---------------------------------------------------------------------------

def select_option(conn, brand_id: str, cycle_id: str, actor: str,
                  option_id: Optional[str] = None) -> None:
    """老闆選定一個方案。省略 option_id 時預設選 AI 推薦的那個。

    失敗一律拋 ValueError（比照 approve()），呼叫端接住轉人話訊息。
    """
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if cycle is None:
        raise ValueError(f"找不到廣告檔期：{cycle_id}")

    options = get_pending_options(conn, brand_id, cycle_id)
    if not options:
        raise ValueError("這期還沒有可選的方案，請先產生方案。")

    if option_id:
        chosen = next((o for o in options if o["id"] == option_id), None)
        if chosen is None:
            raise ValueError("找不到這個方案，可能已經重新產生過了，麻煩重新整理頁面再選一次。")
    else:
        chosen = next((o for o in options if o["is_recommended"]), options[0])

    plan = {
        "summary": chosen["summary"],
        "difference": chosen.get("difference", ""),
        "audience": chosen["audience"],
        "angles": chosen["angles"],
        "hypotheses": chosen["hypotheses"],
        "grounding": chosen["grounding"],
        "llm_task_id": chosen.get("llm_task_id"),
        "methodology_missing": chosen.get("methodology_missing") or [],
    }
    _persist(conn, brand_id, cycle, plan, actor)
    conn.execute(
        "DELETE FROM campaign_plan_option WHERE brand_id = ? AND campaign_cycle_id = ?",
        (brand_id, cycle_id),
    )
    conn.commit()


def _persist(conn, brand_id: str, cycle: dict, plan: dict, actor: str) -> None:
    """把選定的方案寫成正式計畫新版本，並建立對應的測試格與策略假設。"""
    cycle_id = cycle["id"]
    version = (cycle["plan_version"] or 0) + 1
    ts = now_iso()

    conn.execute(
        "INSERT INTO campaign_plan (id, campaign_cycle_id, brand_id, plan_version, plan_json,"
        " status, approved_by, approved_at, created_at) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?)",
        (new_id("cpl"), cycle_id, brand_id, version,
         json.dumps(plan, ensure_ascii=False), "draft", ts),
    )

    # 每個切角一格測試格：票 6 的素材掛上去，成效才回溯得到是哪個切角有效。
    # 重生成計畫時先清掉舊格——舊格底下若已有素材，外鍵會擋下刪除，此時保留舊格不動。
    try:
        conn.execute(
            "DELETE FROM experiment_cell WHERE brand_id = ? AND campaign_cycle_id = ?",
            (brand_id, cycle_id),
        )
    except Exception:
        pass

    valid_product_ids = {
        row["product_id"] for row in ads_repo.list_cycle_products(conn, brand_id, cycle_id)
    }
    audience_text = audience_summary_text(plan["audience"])
    for angle in plan["angles"]:
        product_id = angle["product_id"] if angle["product_id"] in valid_product_ids else None
        conn.execute(
            "INSERT INTO experiment_cell (id, campaign_cycle_id, brand_id, product_id, audience,"
            " creative_angle, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (new_id("exc"), cycle_id, brand_id, product_id, audience_text,
             angle["title"], ts),
        )

    # 策略假設住品牌智庫（跨模組），這裡只透過它的公開函式建立，再用連結表引用。
    for hypothesis in plan["hypotheses"]:
        created = bi.create_strategy_hypothesis(
            conn, brand_id, hypothesis_type=hypothesis["type"],
            statement=hypothesis["statement"], created_by=actor, actor=actor,
            source_cycle_id=cycle_id,
        )
        conn.execute(
            "INSERT OR IGNORE INTO campaign_cycle_hypothesis (campaign_cycle_id,"
            " strategy_hypothesis_id, brand_id, role) VALUES (?, ?, ?, ?)",
            (cycle_id, created["id"], brand_id, hypothesis["type"]),
        )

    conn.execute(
        "UPDATE campaign_cycle SET plan_version = ?, status = 'REVIEW', updated_at = ?"
        " WHERE brand_id = ? AND id = ?",
        (version, ts, brand_id, cycle_id),
    )
    conn.commit()


def get_latest_plan(conn, brand_id: str, cycle_id: str) -> Optional[dict]:
    """最新一版計畫（含解析好的 plan dict）。沒有就回 None。"""
    row = conn.execute(
        "SELECT * FROM campaign_plan WHERE brand_id = ? AND campaign_cycle_id = ?"
        " ORDER BY plan_version DESC LIMIT 1",
        (brand_id, cycle_id),
    ).fetchone()
    if row is None:
        return None
    plan = dict(row)
    plan["plan"] = json.loads(plan["plan_json"])
    return plan


MAX_ANGLE_LENGTH = 30  # 票 04-angle-rename 決議：畫面輸入框上限


def get_cell(conn, brand_id: str, cycle_id: str, cell_id: str) -> Optional[dict]:
    """單一切角格（票 04-angle-rename：改名路由用來查 404、取改名前的值）。放在這裡而不是
    `app/ads/repository.py`：那檔已經超標凍在 `KNOWN_OVERSIZED_FILES`（見 docs/tech-debt.md），
    只准變小不准再加。"""
    row = conn.execute(
        "SELECT * FROM experiment_cell WHERE brand_id = ? AND campaign_cycle_id = ? AND id = ?",
        (brand_id, cycle_id, cell_id),
    ).fetchone()
    return dict(row) if row else None


def list_cell_angles(conn, brand_id: str, cycle_id: str) -> list:
    """這期切角格目前的名字（id＋現名）。提案書畫面要以這份為準，不是 plan_json 快照——
    改名後快照裡的角度標題就跟 cell 對不上了（票 04-angle-rename 一.3）。"""
    return [dict(r) for r in conn.execute(
        "SELECT id, creative_angle FROM experiment_cell WHERE brand_id = ? AND campaign_cycle_id = ?"
        " ORDER BY rowid", (brand_id, cycle_id))]  # 寫入順序＝plan.angles 順序；id 同一毫秒內隨機，不能當排序


def rename_angle(conn, brand_id: str, cycle_id: str, cell: dict, creative_angle: str,
                 actor: str) -> str:
    """就地改名 experiment_cell.creative_angle（票 04-angle-rename 決議：不動 schema）。
    呼叫端已經查過 cell 存在（404 由路由層處理，這裡收已查到的那一列）——這裡只管「能不能
    改」與留稽核。已生成的素材主題不動、不重生（決議原文）：主題生成時才會現查 cell，
    改名自然只影響之後才生的，這裡不用額外處理。"""
    creative_angle = (creative_angle or "").strip()
    if not creative_angle:
        raise ValueError("切角名稱不能空白")
    if len(creative_angle) > MAX_ANGLE_LENGTH:
        raise ValueError(f"切角名稱最多 {MAX_ANGLE_LENGTH} 字")
    if ads_handoff.has_publishing_package(conn, brand_id, cycle_id):
        raise ValueError("交接包已產出，改名會讓 Meta 上的名稱對不上。")

    conn.execute("UPDATE experiment_cell SET creative_angle = ? WHERE id = ?",
                (creative_angle, cell["id"]))
    write_audit(conn, brand_id=brand_id, entity_type="experiment_cell", entity_id=cell["id"],
               action="rename_angle", actor=actor,
               before={"creative_angle": cell["creative_angle"]},
               after={"creative_angle": creative_angle})
    conn.commit()
    return creative_angle


def approve(conn, brand_id: str, cycle_id: str, actor: str) -> None:
    """關卡一：使用者確認計畫。計畫版本凍結，檔期進入做素材階段。"""
    plan = get_latest_plan(conn, brand_id, cycle_id)
    if plan is None:
        raise ValueError("這期還沒有計畫可以確認")
    ts = now_iso()
    conn.execute(
        "UPDATE campaign_plan SET status = 'approved', approved_by = ?, approved_at = ?"
        " WHERE id = ?",
        (actor, ts, plan["id"]),
    )
    ads_repo.update_cycle_status(conn, brand_id, cycle_id, status="PRODUCTION", actor=actor)
