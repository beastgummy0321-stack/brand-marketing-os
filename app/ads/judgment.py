"""app/ads/judgment.py — F04-I08: 首頁四塊與 Campaign 清單頁要印的每一句判斷，全部在這裡組成
字串，隨 payload 出去、瀏覽器原樣印（ARCHITECTURE.md §6.1 第 10 條）。純函式：沒有 SQL、沒有
LLM、沒有 `datetime.now()`（今天的日期一律由呼叫端傳進來，同 `app/core/settings.py::
today_for_org` 的慣例）。私有：`app/ads/` 自己的檔案（`repository.py`／`routes.py`／
`closeout.py`／`strategy.py`）import 這個檔案（container contract §1），外部只透過
`app.ads.__init__` 的公開入口。

`conversion_labels`（F05-I12）：這個品牌的「購買」該叫什麼——「每筆名單成本」與 CPA 是同一個
算式（花費÷轉換數）的兩個名字，不新增 `success_metric` 的值（ARCHITECTURE.md §8 第 4 條）。

`campaign_judgment` 吃的是「一整列 campaign row，外加呼叫端算好的 `budget_total`／`spend`」，
不是重新去 DB 查——`repository.py` 已經把這兩個數字算出來一次（`_budget_total`／
`_outcome_totals`），這裡不重算第二遍。
"""

from datetime import date, timedelta
from typing import Any

_VERDICT_TEXT = {
    "達成": "已結案，達成成功條件",
    "未達成": "已結案，未達成成功條件",
}

_KIND_TITLES = {
    "publish": "發布了 {name}",
    "bind": "配對了 {name}",
    "budget": "調整了 {name} 的預算",
    "date": "調整了 {name} 的投放期間",
    "pause": "暫停了 {name}",
    "creative": "更新了 {name} 的素材",
}

_SYNC_STATE_TEXT = {
    "pending_manual": "待手動同步",
    "confirmed_manual": "已手動同步",
    "auto_synced": "自動同步",
}

_MONEY_KEYS = frozenset({"daily_budget", "budget_planned", "total_budget"})

_BUDGET_TIME_GAP = 0.15


def _fmt_money(amount) -> str:
    return f"NT$ {round(float(amount)):,}"


def _fmt_date(d: date) -> str:
    return f"{d.month}月{d.day}日"


def _as_date(value):
    """DB 欄位常是 `date`；`created_at`／`closed_at` 是 `datetime`——兩邊都可能出現，統一
    取出 `date` 那一半。"""
    if value is None:
        return None
    return value.date() if hasattr(value, "date") else value


def _live_judgment(campaign: dict[str, Any]) -> dict:
    """text/detail 只講看得到的事實，不講原因（ARCHITECTURE.md §0：相關永遠不報成因果）。"""
    start_date = campaign.get("start_date")
    end_date = campaign.get("end_date")
    budget_total = campaign.get("budget_total")
    spend = campaign.get("spend")

    if not budget_total or start_date is None or end_date is None:
        return {"tone": "neutral", "text": "投放中", "detail": "還沒有可比的總預算"}

    days = (end_date - start_date).days + 1
    today = campaign["_today"]
    day_n = min(max((today - start_date).days + 1, 1), days) if days > 0 else None
    if day_n is None:
        return {"tone": "neutral", "text": "投放中", "detail": "還沒有可比的總預算"}

    if spend is None:
        return {
            "tone": "neutral", "text": "投放中",
            "detail": f"還沒有花費資料・第 {day_n}／{days} 天",
        }

    budget_pct = spend / float(budget_total)
    time_pct = day_n / days
    detail = (
        f"已花費 {_fmt_money(spend)} ／ 總預算 {_fmt_money(budget_total)}"
        f"・第 {day_n}／{days} 天"
    )

    diff = budget_pct - time_pct
    if diff > _BUDGET_TIME_GAP:
        return {"tone": "warn", "text": "投放中，預算花得比時間快", "detail": detail}
    if diff < -_BUDGET_TIME_GAP:
        return {"tone": "neutral", "text": "投放中，預算花得比時間慢", "detail": detail}
    return {"tone": "good", "text": "投放中，預算與時間同步", "detail": detail}


def campaign_judgment(campaign: dict[str, Any], *, today: date) -> dict:
    """回 `{"tone": "neutral"|"good"|"warn", "text": str, "detail": str}`。第一個命中的規則
    就是答案（見票面表格）。`campaign` 至少要有 `status`／`verdict`／`closed_at`／`end_date`／
    `start_date`／`budget_basis_json`（campaign row 原欄位）加上 `budget_total`／`spend`
    （呼叫端算好的衍生值）。"""
    if campaign.get("origin") == "imported":
        return {"tone": "neutral", "text": "既有活動工作區",
                "detail": "平台狀態與工作區分開；成功條件待確認。"}
    status = campaign.get("status")

    if status == "closed":
        text = _VERDICT_TEXT.get(str(campaign.get("verdict") or ""), "已結案，看不出來")
        closed_date = _as_date(campaign.get("closed_at"))
        detail = f"結案於 {_fmt_date(closed_date)}" if closed_date else "結案於未知日期"
        return {"tone": "neutral", "text": text, "detail": detail}

    if status == "ended":
        end_date = campaign.get("end_date")
        detail = (
            f"結束於 {_fmt_date(end_date)}，7 天後自動結案"
            if end_date is not None else "已結束，7 天後自動結案"
        )
        return {"tone": "neutral", "text": "投放已結束，還沒結案", "detail": detail}

    if status == "live":
        return _live_judgment({**campaign, "_today": today})

    if status == "ready":
        start_date = campaign.get("start_date")
        detail = f"預計 {_fmt_date(start_date)} 上線" if start_date is not None \
            else "還沒設定投放期間"
        return {"tone": "neutral", "text": "投放結構已就緒，還沒發布", "detail": detail}

    # status == "draft"
    has_strategy = bool((campaign.get("budget_basis_json") or {}).get("strategy"))
    if has_strategy:
        return {
            "tone": "neutral", "text": "策略已產生，還沒採用",
            "detail": "下一步：選預算情境並採用策略",
        }
    return {"tone": "neutral", "text": "還沒產生策略", "detail": "下一步：產生策略建議"}


def brand_headline(counts: dict[str, int]) -> dict:
    """回 `{"text": str, "facts": str}`。`counts` 是 `{"running", "upcoming", "ended",
    "needs_decision"}` 四個數字。"""
    running = counts.get("running", 0)
    upcoming = counts.get("upcoming", 0)
    ended = counts.get("ended", 0)
    needs_decision = counts.get("needs_decision", 0)

    if running > 0:
        text = f"目前有 {running} 個 Campaign 進行中"
    elif upcoming > 0:
        text = f"還沒有進行中的 Campaign，有 {upcoming} 個即將上線"
    else:
        text = "這個品牌還沒有 Campaign"

    parts = []
    if upcoming:
        parts.append(f"{upcoming} 個即將上線")
    if ended:
        parts.append(f"{ended} 個已結束")
    if needs_decision:
        parts.append(f"{needs_decision} 件需要你決定的事")
    else:
        parts.append("目前沒有需要你決定的事")
    return {"text": text, "facts": "・".join(parts)}


# F05-I12：「每筆名單成本」與 CPA 是同一個算式（花費÷轉換數）的兩個名字——不新增
# success_metric 的值，只換 label（§8 第 4 條）。`purchase`／`None`／未知值一律落在購買這行。
_CONVERSION_LABELS = {
    "purchase": {"conversion": "購買", "count": "購買數", "cpa": "每次購買成本"},
    "lead": {"conversion": "名單", "count": "名單數", "cpa": "每筆名單成本"},
    "booking": {"conversion": "預約", "count": "預約數", "cpa": "每次預約成本"},
    "awareness": {"conversion": "成效", "count": "成效次數", "cpa": "每次成效成本"},
}


def conversion_labels(conversion_goal: str | None) -> dict:
    """品牌 `conversion_goal` -> 這個品牌的投放中心該用哪三個詞。未知值退回購買（原本
    F05 之前唯一的行為，不是猜——沒設定就是還沒設定，購買是安全的預設印法）。"""
    if conversion_goal is None:
        return _CONVERSION_LABELS["purchase"]
    return _CONVERSION_LABELS.get(conversion_goal, _CONVERSION_LABELS["purchase"])


def _format_field_value(key: str, value: Any) -> str:
    if key in _MONEY_KEYS and value is not None:
        return _fmt_money(value)
    return str(value)


def _change_detail(before: dict[str, Any], after: dict[str, Any]) -> str | None:
    """`before_json`／`after_json` 是自由形狀（§0）：只挑 `after` 裡真的變動過的鍵，不把整段
    JSON 原樣印給使用者看。取不到鍵就整段省略（回 `None`），由呼叫端接手預設句。"""
    changes = []
    for key, new in after.items():
        old = before.get(key)
        if old == new:
            continue
        if old is None:
            changes.append(f"設定為 {_format_field_value(key, new)}")
        else:
            changes.append(f"{_format_field_value(key, old)} → {_format_field_value(key, new)}")
    return "、".join(changes) if changes else None


def _time_text(created_at: Any, *, today: date) -> str:
    created_date = _as_date(created_at) or today
    time_str = created_at.strftime("%H:%M") if hasattr(created_at, "strftime") else ""
    if created_date == today:
        return f"今天 {time_str}"
    if created_date == today - timedelta(days=1):
        return f"昨天 {time_str}"
    return f"{created_date.month}月{created_date.day}日 {time_str}"


def action_line(action: dict[str, Any], *, campaign_name: str, target_name: str | None,
                today: date) -> dict:
    """回 `{"time_text", "title", "detail"}`——`ads_action` 一列的三句話。"""
    name = target_name or campaign_name
    kind = str(action["kind"])
    title = _KIND_TITLES.get(kind, kind).format(name=name)

    detail = None
    if kind in ("budget", "date"):
        detail = _change_detail(action.get("before_json") or {}, action.get("after_json") or {})
    if detail is None:
        sync_text = _SYNC_STATE_TEXT.get(str(action.get("sync_state") or ""), "")
        detail = sync_text or "已記錄"

    return {
        "time_text": _time_text(action["created_at"], today=today),
        "title": title,
        "detail": detail,
    }
