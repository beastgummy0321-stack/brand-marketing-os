# -*- coding: utf-8 -*-
"""app/ads/guardrails.py — 護欄純函數（票 3）：對帳、增幅上限、數字合理性。

ADHD 設計輸入（docs/design/14）方向一的落點。三件事：

1. `reconcile()`：交接包上的計畫 vs Meta 上的實際，對不上就產 Finding。
2. `cap_scale_up()`：「擴大」建議的預算過上限，與轉換樣本數掛鉤——樣本最少時最保守。
3. `check_data_sanity()`：成效數字進資料庫前的合理性海關。

**全部只標示、不擋路**（決策 0013）：Finding 的 severity 只有 info／warn，沒有 block。
判讀照跑，但可信度依 confidence_penalty 打折。

Finding 是統一結構：API 自動比對、CSV 降級版的三題自答、法務掃描、增幅上限，
產出的都是這一種（對應 `finding` 資料表）。日後 API 接上，只是多一個 Finding 來源，
下游完全不用改（ADHD 設計輸入原話）。

本檔不呼叫 LLM、不碰資料庫、不讀系統時間。
"""

from dataclasses import dataclass, field
from typing import Optional

# --- 門檻常數（要調就改這裡）-------------------------------------------------

# 花費偏移門檻。Meta 允許單日花費超出日預算約 25%（以週總額守恆），所以 25% 以內是這個平台
# 的正常呼吸，不該報警——ADHD 設計輸入點名的「狼來了」風險就是死在門檻拍太緊。
# 真實帳戶跑過幾期後，這兩個數字應該用使用者自己的波動重新校準（票 12）。
SPEND_DEVIATION_INFO = 0.15
SPEND_DEVIATION_WARN = 0.25

# 可信度扣分：同一期累積多個 Finding 時相加，由判讀端 clamp 到 0–1。
PENALTY_INFO = 0.1
PENALTY_WARN = 0.3

# 增幅階梯（ADHD 設計輸入方向一）：轉換樣本越少，越不准大幅加碼。
# 防的是「第一期運氣好就十倍 all-in」——樣本 10 筆的成功率，統計上跟擲硬幣差不多。
SCALE_LADDER = [
    (30, 0.20),    # 轉換 < 30 筆：最多 +20%
    (100, 0.50),   # 30–100 筆：最多 +50%
    (None, 1.50),  # > 100 筆：最多 +150%
]

# 合理性海關的物理上限：這些數字出現代表資料本身壞了，不是投放表現差。
MAX_PLAUSIBLE_CTR = 1.0  # 點擊率 100%


@dataclass(frozen=True)
class Finding:
    """一條提醒。欄位對應 `finding` 資料表的同名欄位，可直接落庫。"""

    finding_type: str          # reconciliation/external_change/budget_cap/data_sanity
    code: str                  # 機器可讀，供測試與統計
    severity: str              # info/warn（刻意沒有 block）
    message: str               # 人話，介面直接顯示（鐵則 12：不得出現內部代號）
    source: str                # api_diff/self_answer/pure_function
    confidence_penalty: float = 0.0
    evidence: dict = field(default_factory=dict)


def _pct(value: float) -> str:
    return f"{abs(value) * 100:.0f}%"


# --- 1. 對帳 ----------------------------------------------------------------

def reconcile(plan: dict, actuals: dict, source: str = "api_diff") -> list[Finding]:
    """比對計畫與實際，回傳 Finding 清單（沒問題就回空清單）。

    plan：交接包當初給的數字，至少要有 `total_budget`；可另有 `daily_budget`、
    `start_date`、`end_date`。
    actuals：Meta 上的實際值，鍵名同上；缺哪個鍵就不比哪一項（CSV 軌只拿得到 `spend`）。

    source 決定這批 Finding 的來源標記：`api_diff` 是自動比對，`self_answer` 是使用者
    回答三題降級版產生的——兩者結構相同，日後 API 接上不必改下游。
    """
    findings: list[Finding] = []

    planned_total = plan.get("total_budget")
    actual_spend = actuals.get("spend")
    if planned_total and actual_spend is not None:
        deviation = (actual_spend - planned_total) / planned_total
        if abs(deviation) >= SPEND_DEVIATION_INFO:
            over = deviation > 0
            warn = abs(deviation) >= SPEND_DEVIATION_WARN
            findings.append(Finding(
                finding_type="reconciliation",
                code="spend_over_plan" if over else "spend_under_plan",
                severity="warn" if warn else "info",
                message=(
                    f"實際花費比計畫{'多' if over else '少'}了 {_pct(deviation)}"
                    f"（計畫 {planned_total:,.0f}、實際 {actual_spend:,.0f}）。"
                    + ("差距不小，這期的判讀結論請當參考就好。" if warn
                       else "還在正常波動範圍，先記著就好。")
                ),
                source=source,
                confidence_penalty=PENALTY_WARN if warn else PENALTY_INFO,
                evidence={"planned_total": planned_total, "actual_spend": actual_spend,
                          "deviation": round(deviation, 4)},
            ))

    planned_daily = plan.get("daily_budget")
    actual_daily = actuals.get("daily_budget")
    if planned_daily and actual_daily is not None and abs(actual_daily - planned_daily) > 0.01:
        findings.append(Finding(
            finding_type="reconciliation",
            code="daily_budget_mismatch",
            severity="warn",
            message=(
                f"Meta 上的每日預算是 {actual_daily:,.0f}，跟交接包寫的 {planned_daily:,.0f} 不一樣。"
                "可能是設定時打錯，也可能是後來手動改過——這會影響判讀準確度。"
            ),
            source=source,
            confidence_penalty=PENALTY_WARN,
            evidence={"planned_daily": planned_daily, "actual_daily": actual_daily},
        ))

    for key, label in (("start_date", "開始日期"), ("end_date", "結束日期")):
        planned_date, actual_date = plan.get(key), actuals.get(key)
        if planned_date and actual_date and planned_date != actual_date:
            findings.append(Finding(
                finding_type="reconciliation",
                code=f"{key}_mismatch",
                severity="info",
                message=(f"Meta 上的{label}是 {actual_date}，交接包寫的是 {planned_date}。"
                         "檔期長度不同會讓成效不好直接比較。"),
                source=source,
                confidence_penalty=PENALTY_INFO,
                evidence={"planned": planned_date, "actual": actual_date},
            ))
    return findings


# 三題降級版（API 掛掉時的退路）：問題與其對應的 Finding。
# 使用者答「不一樣／有」＝命中，產出的 Finding 與 API 自動比對同一種結構。
SELF_ANSWER_QUESTIONS = [
    {
        "key": "budget_same",
        "question": "Meta 上設定的預算，跟交接包寫的一樣嗎？",
        "code": "daily_budget_mismatch",
        "message": "你回報 Meta 上的預算跟交接包不一樣，這期的判讀會打折。",
    },
    {
        "key": "schedule_same",
        "question": "開始與結束日期，跟交接包寫的一樣嗎？",
        "code": "schedule_mismatch",
        "message": "你回報實際檔期跟計畫不同，成效不好跟前幾期直接比較。",
    },
    {
        "key": "other_campaign_running",
        "question": "這段期間，有沒有同時跑其他活動或廣告？",
        "code": "concurrent_campaign",
        "message": "同期還有其他活動在跑，這期的數字沒辦法完全歸因給這批素材。",
    },
]


def self_answer_findings(answers: dict) -> list[Finding]:
    """三題點選式是非題 → Finding（API 掛掉時的退路，決策 0022 第 20 點）。

    answers 形如 `{"budget_same": True, "schedule_same": True,
    "other_campaign_running": False}`。答 None（沒答）視同沒問題，不產 Finding——
    自答是補充資訊，不是新的必填關卡。

    前兩題答 False（不一樣）算命中；第三題答 True（有其他活動在跑）算命中。
    """
    findings = []
    for item in SELF_ANSWER_QUESTIONS:
        answer = answers.get(item["key"])
        if answer is None:
            continue
        hit = answer if item["key"] == "other_campaign_running" else not answer
        if hit:
            findings.append(Finding(
                finding_type="external_change",
                code=item["code"],
                severity="warn",
                message=item["message"],
                source="self_answer",
                confidence_penalty=PENALTY_WARN,
                evidence={"question": item["question"], "answer": answer},
            ))
    return findings


def confidence_from_findings(findings: list[Finding]) -> float:
    """把 Finding 的扣分收斂成 0–1 的本期判讀可信度。1.0 ＝沒有任何疑慮。"""
    penalty = sum(f.confidence_penalty for f in findings)
    return round(max(0.0, min(1.0, 1.0 - penalty)), 2)


# --- 2. 增幅上限 -------------------------------------------------------------

@dataclass(frozen=True)
class ScaleCap:
    current_budget: float
    max_budget: float
    cap_ratio: float
    conversions: float
    capped: bool          # 建議值有沒有被上限砍下來
    finding: Optional[Finding] = None


def cap_scale_up(current_budget: float, conversions: float,
                 proposed_budget: Optional[float] = None) -> ScaleCap:
    """「擴大」建議的預算過上限，上限與轉換樣本數掛鉤。

    proposed_budget 省略時只回傳上限本身（給介面顯示「這期最多可以加到多少」）。
    有傳且超過上限時，`max_budget` 就是實際該用的數字，並附一條人話 Finding 說明為什麼被壓下來。
    """
    if current_budget <= 0:
        raise ValueError("目前預算必須大於 0")

    cap_ratio = next(ratio for threshold, ratio in SCALE_LADDER
                     if threshold is None or conversions < threshold)
    max_budget = round(current_budget * (1 + cap_ratio), 2)

    capped = proposed_budget is not None and proposed_budget > max_budget
    finding = None
    if capped:
        finding = Finding(
            finding_type="budget_cap",
            code="scale_up_capped",
            severity="info",
            message=(
                f"這期只累積了 {conversions:.0f} 筆轉換，樣本還不夠多，"
                f"所以預算最多先加到 {max_budget:,.0f}（原本想加到 {proposed_budget:,.0f}）。"
                "等數據再多一些，可以加的幅度就會放寬。"
            ),
            source="pure_function",
            confidence_penalty=0.0,  # 這不是資料有疑慮，只是保守起見，不扣可信度
            evidence={"current_budget": current_budget, "proposed": proposed_budget,
                      "max_budget": max_budget, "conversions": conversions},
        )
    return ScaleCap(current_budget=current_budget, max_budget=max_budget, cap_ratio=cap_ratio,
                    conversions=conversions, capped=capped, finding=finding)


# --- 3. 合理性海關 -----------------------------------------------------------

def check_data_sanity(row: dict, today: Optional[str] = None) -> list[Finding]:
    """成效數字進資料庫前的體檢。命中就該進隔離區，不進判讀。

    row 用的是正規化後的欄位名（impressions／clicks／spend／conversions／revenue／as_of_date）。
    today 是 'YYYY-MM-DD' 字串，省略就不檢查未來日期——本檔不讀系統時間（純函數）。
    """
    findings: list[Finding] = []

    def add(code: str, message: str, evidence: dict):
        findings.append(Finding(
            finding_type="data_sanity", code=code, severity="warn", message=message,
            source="pure_function", confidence_penalty=PENALTY_WARN, evidence=evidence,
        ))

    impressions, clicks = row.get("impressions"), row.get("clicks")
    if impressions and clicks and clicks > impressions * MAX_PLAUSIBLE_CTR:
        add("ctr_impossible",
            f"這筆資料的點擊數（{clicks:,}）比曝光數（{impressions:,}）還多，數字不合理，"
            "先擱在一旁不列入計算。",
            {"impressions": impressions, "clicks": clicks})

    for key, label in (("spend", "花費"), ("impressions", "曝光數"), ("clicks", "點擊數"),
                       ("conversions", "轉換數"), ("revenue", "營收")):
        value = row.get(key)
        if value is not None and value < 0:
            add("negative_value", f"這筆資料的{label}是負數（{value}），數字不合理，先擱在一旁。",
                {"field": key, "value": value})

    as_of = row.get("as_of_date")
    if today and as_of and as_of > today:
        add("future_date",
            f"這筆資料的日期是 {as_of}，還沒到，先擱在一旁——通常是匯出時選錯區間。",
            {"as_of_date": as_of, "today": today})
    return findings


def demo() -> None:
    """python -m app.ads.guardrails — 最小自檢，順便當用法示範。"""
    # 花在 25% 以內不報警，超過才報
    assert reconcile({"total_budget": 10000}, {"spend": 11000}) == []
    over = reconcile({"total_budget": 10000}, {"spend": 13000})
    assert len(over) == 1 and over[0].severity == "warn", over
    assert confidence_from_findings(over) == 0.7

    # 三題自答：全部答「一樣／沒有」不產 Finding
    assert self_answer_findings({"budget_same": True, "schedule_same": True,
                                 "other_campaign_running": False}) == []
    assert len(self_answer_findings({"budget_same": False})) == 1

    # 增幅階梯：樣本少就保守
    assert cap_scale_up(1000, conversions=10).max_budget == 1200
    assert cap_scale_up(1000, conversions=50).max_budget == 1500
    assert cap_scale_up(1000, conversions=500).max_budget == 2500
    assert cap_scale_up(1000, conversions=10, proposed_budget=10000).capped

    # 合理性海關
    assert len(check_data_sanity({"impressions": 100, "clicks": 500})) == 1
    assert check_data_sanity({"impressions": 1000, "clicks": 50}) == []
    print("guardrails 自檢通過")


if __name__ == "__main__":
    demo()
