"""app/dashboard/guide_cards.py — 下一步指南卡引擎（票 04-guide-card-engine，規格 0001）。

純函數：資料進、結論出，不碰資料庫、不呼叫 LLM。規則採登記制（同 app/core/interrupts.py
CATEGORIES 的類別登記做法）：
RULES 是一個 dict，key＝規則 id，value＝判定函式；dict 順序＝優先序（越早登記代表行動
價值越高，同 interrupts.py `_CATEGORY_RANK` 的做法），呼叫端不得自行排序。

貨源（外殼切片 2026-08-28：pacing_alert／reading_unread／next_cycle_draft／cycle_stage
四條隨 `app/ads/` 一起刪掉——它們判讀的都是廣告檔期，沒有檔期就沒有卡）：
- conversion_goal_missing：品牌沒設定廣告目標（票 C）。方法論的條件過濾整條靠
  brand.conversion_goal，沒設定＝方法論篩選形同沒接電、AI 會套用電商站內交易的
  預設寫法，屬於資料正確性前提，登記在所有規則之前（比 pacing_alert 更早）
- pending_facts：待確認事實數
- campaign_calendar：檔期日曆備戰提醒（票 06-campaign-calendar，純函數在
  app/dashboard/campaign_calendar.py，這裡只負責把結果轉成卡片文字）

每條規則收一份「這個品牌的原始資料」dict（build() 的 facts 參數，由呼叫端組裝——
本檔不碰資料庫，見 app/dashboard/repository.py），判斷觸不觸發；觸發回一張卡
{title, action_url}，不觸發回 None。build() 依登記順序掃過全部規則，取前 MAX_CARDS
筆——沒有任何規則觸發就回空清單（呼叫端負責顯示「一切正常」）。

文字用程式模板，不花 AI 錢（AI 翻人話留待後續，規格 Out of Scope）。

指南卡與打斷佇列分工不混：本檔只讀 facts、只回傳建議清單，不寫入 interrupt 表
（規格「指南卡與打斷佇列分工不變」）。

facts 欄位契約（由 app/dashboard/repository.py 組裝）：
- brand_id: str
- conversion_goal: str|None（票 C：brand.conversion_goal 原始值，None／空字串＝
  沒設定，觸發 conversion_goal_missing）
- pending_facts_count: int
- campaign_reminder: dict|None（app/dashboard/campaign_calendar.py
  next_calendar_reminder() 的回傳值，經 app/dashboard/repository.py
  _attach_last_year_skip() 附帶去年跳過脈絡：{id, name, days_until,
  kind("prep"|"creative"), ...}——kind="prep" 才有 weeks_until／tier_label；
  去年同一節日有跳過紀錄才有 last_year_skipped(True)／last_year_skip_reason(str|None)
  （票 03-cycle-skip-record，純顯示脈絡，不影響本規則觸不觸發）；沒有觸發中的節日
  就是 None）
- intake_draft: {"step": int, "resume_path": str} | None（票 B3-intake：這個品牌有沒有
  進行中的建檔精靈草稿；有就是 `app/intake/state.get_draft()` 回傳草稿的 step／
  resume_path，沒有就是 None）
"""

from collections.abc import Callable

MAX_CARDS = 3


def _rule_conversion_goal_missing(facts: dict) -> dict | None:
    """品牌沒設定廣告目標：方法論的條件過濾整條靠 brand.conversion_goal，沒設定就等於
    沒接電，AI 會套用電商站內交易的預設寫法（票 C 明顯提醒需求）。資料正確性前提，
    優先度高於一般提醒，登記在所有規則之前。"""
    if facts.get("conversion_goal"):
        return None
    return {
        "title": "還沒設定廣告目標——AI 現在會用電商預設值寫文案，可能不適合你",
        # T4 步驟 1 刪掉舊版 Jinja `/brands/{id}/edit`，品牌資料編輯面板現在只能從
        # 品牌智庫頁點「編輯品牌資料」開，沒有能直接開啟面板的網址，導去該頁即可。
        "action_url": f"/app/brands/{facts['brand_id']}/library",
    }


def _rule_intake_in_progress(facts: dict) -> dict | None:
    """建檔精靈有進行中草稿：品牌設定還沒完成，跟 conversion_goal_missing 同樣屬於
    「這個品牌能不能正常運作」的前提，登記在其之後、其餘一般提醒之前（票 B3-intake，
    GRILL-B3-intake.md「拿不準的點」第 3 條裁決：併進本票，卡片形狀沿用既有 API 不新增
    欄位）。「入口存在、點下去去對的地方」用既有 `app/intake/state.py` 的 `_resume_path`
    續接判斷，這裡只轉文字，不重算。"""
    draft = facts.get("intake_draft")
    if not draft:
        return None
    return {
        "title": f"建檔進行中（第 {draft['step']} 步，共 5 步）・繼續建檔",
        "action_url": draft["resume_path"],
    }


def _rule_pending_facts(facts: dict) -> dict | None:
    """待確認事實數：品牌智庫還有事實待確認。"""
    n = facts.get("pending_facts_count") or 0
    if n <= 0:
        return None
    return {
        "title": f"有 {n} 條事實待確認",
        # T4 步驟 1 刪掉舊版 Jinja `/hub/facts` 頁，改導去新殼品牌智庫頁的事實分頁。
        "action_url": f"/app/brands/{facts['brand_id']}/library?tab=facts",
    }


def _rule_campaign_calendar(facts: dict) -> dict | None:
    """檔期日曆備戰提醒（票 06-campaign-calendar）：素材完稿期限比備戰提前期更急迫，
    reminder["kind"] 已經在 next_calendar_reminder() 決定好要顯示哪一種，這裡只轉文字。
    一鍵前往導去品牌頁（外殼切片：`/campaigns/new` 是刪掉的 8 支路由之一，這裡不留死連結）。"""
    reminder = facts.get("campaign_reminder")
    if not reminder:
        return None
    if reminder["kind"] == "creative":
        title = f"「{reminder['name']}」素材要完稿了，還有 {reminder['days_until']} 天"
    else:
        title = f"「{reminder['name']}」還有 {reminder['weeks_until']} 週，開始備戰？"
    # 票 03-cycle-skip-record：去年同一節日有跳過紀錄，附帶顯示去年的理由當脈絡
    # （純顯示，不影響這條規則觸不觸發）。
    if reminder.get("last_year_skipped"):
        reason = reminder.get("last_year_skip_reason")
        title += f"（去年跳過：{reason}）" if reason else "（去年跳過）"
    return {"title": title, "action_url": f"/app/brands/{facts['brand_id']}"}


# 登記表：dict 順序＝優先序（越早登記代表行動價值越高，比照 interrupts.py CATEGORIES）。
RULES: "dict[str, Callable[[dict], dict | None]]" = {
    "conversion_goal_missing": _rule_conversion_goal_missing,
    "intake_in_progress": _rule_intake_in_progress,
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
    assert build({"brand_id": "b", "conversion_goal": "purchase",
                  "pending_facts_count": 0}) == []
    # 票 C：conversion_goal 沒設定時，提醒排在所有規則之前。
    cards = build({"brand_id": "b", "conversion_goal": None, "pending_facts_count": 2})
    assert len(cards) == 2
    assert cards[0]["action_url"] == "/app/brands/b/library"
    assert cards[1]["action_url"] == "/app/brands/b/library?tab=facts"
    # 票 B3-intake：有進行中建檔草稿時出卡，登記在 conversion_goal_missing 之後；
    # 沒有草稿（None）不出卡。
    cards_with_draft = build({"brand_id": "b", "conversion_goal": "purchase",
                              "pending_facts_count": 0,
                              "intake_draft": {"step": 2, "resume_path": "/app/brands/b/intake"}})
    assert cards_with_draft == [{
        "title": "建檔進行中（第 2 步，共 5 步）・繼續建檔",
        "action_url": "/app/brands/b/intake",
    }]
    assert build({"brand_id": "b", "conversion_goal": "purchase", "pending_facts_count": 0,
                  "intake_draft": None}) == []
    print("dashboard.guide_cards 自檢通過")


if __name__ == "__main__":
    demo()
