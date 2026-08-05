# -*- coding: utf-8 -*-
"""app/dashboard/guide_cards.py — 下一步指南卡引擎（票 04-guide-card-engine，規格 0001）。

純函數：資料進、結論出，不碰資料庫、不呼叫 LLM（沿用 app/ads/reading.py judge() 的
判讀狀態機模式）。規則採登記制（同 app/core/interrupts.py CATEGORIES 的類別登記做法）：
RULES 是一個 dict，key＝規則 id，value＝判定函式；dict 順序＝優先序（越早登記代表行動
價值越高，同 interrupts.py `_CATEGORY_RANK` 的做法），呼叫端不得自行排序。

第一批貨源（規格 0001「指南卡第一批貨源」）：
- reading_unread：判讀結果出爐未讀
- next_cycle_draft：下期草案已備好
- cycle_stage：檔期卡在哪道關卡
- pending_facts：待確認事實數
- campaign_calendar：檔期日曆備戰提醒（票 06-campaign-calendar，純函數在
  app/dashboard/campaign_calendar.py，這裡只負責把結果轉成卡片文字）

（pacing 警示是最後一批貨源，見票 08，不在本票範圍。）

每條規則收一份「這個品牌的原始資料」dict（build() 的 facts 參數，由呼叫端組裝——
本檔不碰資料庫，見 app/dashboard/repository.py），判斷觸不觸發；觸發回一張卡
{title, action_url}，不觸發回 None。build() 依登記順序掃過全部規則，取前 MAX_CARDS
筆——沒有任何規則觸發就回空清單（呼叫端負責顯示「一切正常」）。

文字用程式模板，不花 AI 錢（AI 翻人話留待後續，規格 Out of Scope）。

指南卡與打斷佇列分工不混：本檔只讀 facts、只回傳建議清單，不寫入 interrupt 表
（規格「指南卡與打斷佇列分工不變」）。

facts 欄位契約（由 app/dashboard/repository.py 組裝）：
- brand_id: str
- pending_facts_count: int
- active_cycle: {"id": str, "stage_label": str|None} | None
  （stage_label 為 None＝已經在成效格／沒有進行中檔期，不算「卡在哪道關卡」）
- reading_ready: bool（最新一期已經跑過判讀）
- next_cycle_draft_ready: bool（下期草案已經生成）
- campaign_reminder: dict|None（app/dashboard/campaign_calendar.py
  next_calendar_reminder() 的回傳值：{id, name, days_until, kind("prep"|"creative"),
  ...}——kind="prep" 才有 weeks_until／tier_label；沒有觸發中的檔期就是 None）
"""

from typing import Callable, Optional

MAX_CARDS = 3


def _rule_reading_unread(facts: dict) -> Optional[dict]:
    """判讀結果出爐未讀：最新一期已經跑過判讀，但下期草案還沒備好——代表判讀結論
    還沒被人看過拿去用（一旦下期草案生成，判讀結論已經被用掉，不再算「未讀」）。"""
    cycle = facts.get("active_cycle")
    if not cycle or not facts.get("reading_ready") or facts.get("next_cycle_draft_ready"):
        return None
    return {
        "title": "本期判讀結果已出爐，還沒看",
        "action_url": f"/brands/{facts['brand_id']}/ads/{cycle['id']}/performance",
    }


def _rule_next_cycle_draft(facts: dict) -> Optional[dict]:
    """下期草案已備好：判讀完成後系統已經生出下期草案（預算建議／規則卡），等人確認。"""
    cycle = facts.get("active_cycle")
    if not cycle or not facts.get("next_cycle_draft_ready"):
        return None
    return {
        "title": "下期草案已備好，等你確認",
        "action_url": f"/brands/{facts['brand_id']}/ads/{cycle['id']}/performance",
    }


def _rule_cycle_stage(facts: dict) -> Optional[dict]:
    """檔期卡在哪道關卡：還沒進到成效格（1–4 格）就提醒去推進；已在成效格
    （stage_label 為 None）不算卡住，不提醒。"""
    cycle = facts.get("active_cycle")
    if not cycle:
        return None
    stage_label = cycle.get("stage_label")
    if not stage_label:
        return None
    return {
        "title": f"檔期卡在「{stage_label}」，去推進",
        "action_url": f"/brands/{facts['brand_id']}/ads/{cycle['id']}",
    }


def _rule_pending_facts(facts: dict) -> Optional[dict]:
    """待確認事實數：品牌智庫還有事實待確認。"""
    n = facts.get("pending_facts_count") or 0
    if n <= 0:
        return None
    return {
        "title": f"有 {n} 條事實待確認",
        "action_url": f"/brands/{facts['brand_id']}/hub/facts",
    }


def _rule_campaign_calendar(facts: dict) -> Optional[dict]:
    """檔期日曆備戰提醒（票 06-campaign-calendar）：素材完稿期限比備戰提前期更急迫，
    reminder["kind"] 已經在 next_calendar_reminder() 決定好要顯示哪一種，這裡只轉文字。
    一鍵前往固定導去「開檔期」（規格範例：「農曆新年還有 4 週，開始備戰？」）。"""
    reminder = facts.get("campaign_reminder")
    if not reminder:
        return None
    if reminder["kind"] == "creative":
        title = f"「{reminder['name']}」素材要完稿了，還有 {reminder['days_until']} 天"
    else:
        title = f"「{reminder['name']}」還有 {reminder['weeks_until']} 週，開始備戰？"
    return {"title": title, "action_url": f"/brands/{facts['brand_id']}/ads/new"}


# 登記表：dict 順序＝優先序（越早登記代表行動價值越高，比照 interrupts.py CATEGORIES）。
RULES: "dict[str, Callable[[dict], Optional[dict]]]" = {
    "reading_unread": _rule_reading_unread,
    "next_cycle_draft": _rule_next_cycle_draft,
    "cycle_stage": _rule_cycle_stage,
    "pending_facts": _rule_pending_facts,
    "campaign_calendar": _rule_campaign_calendar,
}


def build(facts: dict) -> list:
    """依登記順序掃過全部規則，取前 MAX_CARDS 筆觸發的卡。沒觸發任何規則就回空清單。"""
    cards = []
    for rule in RULES.values():
        card = rule(facts)
        if card:
            cards.append(card)
        if len(cards) >= MAX_CARDS:
            break
    return cards


def demo() -> None:
    """python -m app.dashboard.guide_cards —— 純函數的最小自檢（無需資料庫）。"""
    assert build({"brand_id": "b", "pending_facts_count": 0, "active_cycle": None,
                  "reading_ready": False, "next_cycle_draft_ready": False}) == []
    cards = build({"brand_id": "b", "pending_facts_count": 2,
                  "active_cycle": {"id": "c1", "stage_label": "素材"},
                  "reading_ready": False, "next_cycle_draft_ready": False})
    assert len(cards) == 2
    assert cards[0]["action_url"] == "/brands/b/ads/c1"
    print("dashboard.guide_cards 自檢通過")


if __name__ == "__main__":
    demo()
