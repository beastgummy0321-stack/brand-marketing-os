"""app/dashboard/guide_cards.py — 下一步指南卡引擎（票 04-guide-card-engine，規格 0001）。

純函數：資料進、結論出，不碰資料庫、不呼叫 LLM（沿用 app/ads/reading.py judge() 的
判讀狀態機模式）。規則採登記制（同 app/core/interrupts.py CATEGORIES 的類別登記做法）：
RULES 是一個 dict，key＝規則 id，value＝判定函式；dict 順序＝優先序（越早登記代表行動
價值越高，同 interrupts.py `_CATEGORY_RANK` 的做法），呼叫端不得自行排序。

第一批貨源（規格 0001「指南卡第一批貨源」，六種到齊）：
- conversion_goal_missing：品牌沒設定廣告目標（票 C）。方法論的條件過濾整條靠
  brand.conversion_goal，沒設定＝方法論篩選形同沒接電、AI 會套用電商站內交易的
  預設寫法，屬於資料正確性前提，登記在所有規則之前（比 pacing_alert 更早）
- pacing_alert：pacing 警示（票 08 產生的打斷佇列事件，這裡轉成行動卡；錢的步調
  在一般提醒裡最優先，登記在 conversion_goal_missing 之後、其餘規則之前）
- reading_unread：判讀結果出爐未讀
- next_cycle_draft：下期草案已備好
- cycle_stage：檔期卡在哪道關卡
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
- active_cycle: {"id": str, "stage_label": str|None} | None
  （stage_label 為 None＝已經在成效格／沒有進行中檔期，不算「卡在哪道關卡」）
- reading_ready: bool（最新一期已經跑過判讀）
- next_cycle_draft_ready: bool（下期草案已經生成）
- campaign_reminder: dict|None（app/dashboard/campaign_calendar.py
  next_calendar_reminder() 的回傳值，經 app/dashboard/repository.py
  _attach_last_year_skip() 附帶去年跳過脈絡：{id, name, days_until,
  kind("prep"|"creative"), ...}——kind="prep" 才有 weeks_until／tier_label；
  去年同一節日有跳過紀錄才有 last_year_skipped(True)／last_year_skip_reason(str|None)
  （票 03-cycle-skip-record，純顯示脈絡，不影響本規則觸不觸發）；沒有觸發中的檔期
  就是 None）
- pacing_alert: {"kind": "overspend"|"underspend", "action_url": str|None,
  "cycle_label": str|None} | None（brand 目前未結的 pacing 打斷事件，list_open 排序後
  第一筆；沒有就是 None。cycle_label 是該檔期的日期區間，B0-15：品牌同時有好幾期進行中
  時，卡片標題要講清楚是哪一期，跟駕駛艙其他連結指到不同檔期不會沒頭沒尾）
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


def _rule_pacing_alert(facts: dict) -> dict | None:
    """pacing 警示轉行動卡：預算步調出問題是「錢的事」，行動價值最高、登記在第一位。
    卡片只給行動入口，事件本體仍在警示區／打斷佇列（規格：pacing 同時是指南卡貨源）。"""
    alert = facts.get("pacing_alert")
    if not alert:
        return None
    base_title = ("檔期預算燒太快，去看步調" if alert["kind"] == "overspend"
                 else "檔期預算花不完，去看步調")
    # B0-15：附上檔期日期區間——駕駛艙上不只一期進行中時，卡片要講清楚是哪一期。
    title = f"{base_title}（{alert['cycle_label']}）" if alert.get("cycle_label") else base_title
    return {"title": title, "action_url": alert.get("action_url")
            or f"/app/brands/{facts['brand_id']}/campaigns"}


def _rule_reading_unread(facts: dict) -> dict | None:
    """判讀結果出爐未讀：最新一期已經跑過判讀，但下期草案還沒備好——代表判讀結論
    還沒被人看過拿去用（一旦下期草案生成，判讀結論已經被用掉，不再算「未讀」）。"""
    cycle = facts.get("active_cycle")
    if not cycle or not facts.get("reading_ready") or facts.get("next_cycle_draft_ready"):
        return None
    return {
        "title": "本期判讀結果已出爐，還沒看",
        # T4 大清倉第 2 刀刪掉舊版 Jinja 成效頁，判讀結論現在顯示在新殼作戰室的成效步驟
        # （frontend/src/components/warroom/steps/PerformanceStep.tsx），導去同一個
        # 檔期頁面即可（跟 _rule_cycle_stage 同一個目的地）。
        "action_url": f"/app/brands/{facts['brand_id']}/campaigns/{cycle['id']}",
    }


def _rule_next_cycle_draft(facts: dict) -> dict | None:
    """下期草案已備好：判讀完成後系統已經生出下期草案（預算建議／規則卡），等人確認。"""
    cycle = facts.get("active_cycle")
    if not cycle or not facts.get("next_cycle_draft_ready"):
        return None
    return {
        "title": "下期草案已備好，等你確認",
        # 同上：舊版 Jinja 成效頁已刪，導去新殼作戰室的同一個檔期頁面。
        "action_url": f"/app/brands/{facts['brand_id']}/campaigns/{cycle['id']}",
    }


def _rule_cycle_stage(facts: dict) -> dict | None:
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
        "action_url": f"/app/brands/{facts['brand_id']}/campaigns/{cycle['id']}",
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
    一鍵前往固定導去「開檔期」（規格範例：「農曆新年還有 4 週，開始備戰？」）。"""
    reminder = facts.get("campaign_reminder")
    if not reminder:
        return None
    if reminder["kind"] == "creative":
        title = f"「{reminder['name']}」素材要完稿了，還有 {reminder['days_until']} 天"
    else:
        title = f"「{reminder['name']}」還有 {reminder['weeks_until']} 週，開始備戰？"
    # 票 03-cycle-skip-record：去年同一節日有跳過紀錄，附帶顯示去年的理由當脈絡
    # （純顯示，不影響這條規則觸不觸發，也不影響 app/ads/nextcycle.py 下期建議引擎）。
    if reminder.get("last_year_skipped"):
        reason = reminder.get("last_year_skip_reason")
        title += f"（去年跳過：{reason}）" if reason else "（去年跳過）"
    return {"title": title, "action_url": f"/app/brands/{facts['brand_id']}/campaigns/new"}


# 登記表：dict 順序＝優先序（越早登記代表行動價值越高，比照 interrupts.py CATEGORIES）。
RULES: "dict[str, Callable[[dict], dict | None]]" = {
    "conversion_goal_missing": _rule_conversion_goal_missing,
    "intake_in_progress": _rule_intake_in_progress,
    "pacing_alert": _rule_pacing_alert,
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
    assert build({"brand_id": "b", "conversion_goal": "purchase", "pending_facts_count": 0,
                  "active_cycle": None, "reading_ready": False,
                  "next_cycle_draft_ready": False}) == []
    cards = build({"brand_id": "b", "conversion_goal": "purchase", "pending_facts_count": 2,
                  "active_cycle": {"id": "c1", "stage_label": "素材"},
                  "reading_ready": False, "next_cycle_draft_ready": False})
    assert len(cards) == 2
    assert cards[0]["action_url"] == "/brands/b/ads/c1"
    # 票 C：conversion_goal 沒設定時，提醒排在所有規則之前（比照卡片數上限也蓋得住）。
    cards_missing_goal = build({"brand_id": "b", "conversion_goal": None,
                                "pending_facts_count": 2,
                                "active_cycle": {"id": "c1", "stage_label": "素材"},
                                "reading_ready": False, "next_cycle_draft_ready": False})
    assert len(cards_missing_goal) == 3
    assert cards_missing_goal[0]["action_url"] == "/app/brands/b/library"
    # 票 B3-intake：有進行中建檔草稿時出卡，登記在 conversion_goal_missing 之後、
    # pacing_alert 之前；沒有草稿（None）不出卡。
    cards_with_draft = build({"brand_id": "b", "conversion_goal": "purchase",
                              "pending_facts_count": 0, "active_cycle": None,
                              "reading_ready": False, "next_cycle_draft_ready": False,
                              "intake_draft": {"step": 2, "resume_path": "/app/brands/b/intake"}})
    assert len(cards_with_draft) == 1
    assert cards_with_draft[0] == {
        "title": "建檔進行中（第 2 步，共 5 步）・繼續建檔",
        "action_url": "/app/brands/b/intake",
    }
    assert build({"brand_id": "b", "conversion_goal": "purchase", "pending_facts_count": 0,
                  "active_cycle": None, "reading_ready": False,
                  "next_cycle_draft_ready": False, "intake_draft": None}) == []
    print("dashboard.guide_cards 自檢通過")


if __name__ == "__main__":
    demo()
