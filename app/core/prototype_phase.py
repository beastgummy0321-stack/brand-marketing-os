"""app/core/prototype_phase.py — 原型階段結束旗標（修憲落地 A6，決策 0037 第一節）。

「原型階段」＝第一次用真錢跑完一期即結束（決策 0037 第 1 條，使用者 2026-08-03 裁決）。
判定方式：檔期結算完成（`app/ads/reading.finalize()`，全系統唯一把檔期轉 CLOSED 之處）
且該期實際花費 > 0。旗標是一次性事件：一旦設定就不再檢查、也沒有清除的函式。

到期提醒的四項豁免內容必須反映現況，不是照抄決策 0037 寫下時的舊清單——見 EXEMPTIONS，
逐項現況由修憲落地 A6 票撰寫時盤點（2026-08-03）。之後這四項若真的被重新決定，
直接砍掉對應項目，不要留著假裝還沒決定過。
"""


from app.core import interrupts as core_interrupts
from app.core import settings as core_settings
from app.core.audit import write_audit
from app.core.db import now_iso

FLAG_SETTING = "prototype_phase_ended_at"

# 決策 0037 第一節第 2 條的四項豁免，逐項附現況（2026-08-03 盤點）。
EXEMPTIONS = [
    {
        "item": "明文 API 金鑰入庫",
        "status": "修憲落地 M4 已把環境變數 ANTHROPIC_API_KEY 設為優先來源"
                  "（app/core/settings.py get_api_key）；DB 回退仍會存明文、仍隨 backups/ 外流"
                  "（決策 0008）。待決：要不要拿掉 DB 回退這條路徑。",
    },
    {
        "item": "全域單一無鎖連線",
        "status": "修憲落地 M3 已加鎖（app/core/db.py _LockingConnection，"
                  "序列化所有進出 sqlite3 底層的呼叫）；仍是單一連線、不是連線池。"
                  "待決：要不要拆連線池。",
    },
    {
        "item": "等待頁進度只存記憶體",
        "status": "未變動：app/ads/routes.py 的 _progress_state 仍是模組級 dict，"
                  "重啟即失。待決：要不要把進度落地到 DB。",
    },
    {
        "item": "專案資料路徑",
        "status": "DB、備份與上傳目錄的預設值都由模組位置推導專案根，"
                  "BRAND_OS_DB／BRAND_OS_BACKUP_DIR／BRAND_OS_UPLOADS 仍可覆寫。"
                  "待決：原型結束後要不要改成強制由部署環境明確指定資料目錄。",
    },
]

_REMINDER_MESSAGE = "原型階段已結束，4項技術豁免待重新決定"


def has_ended(conn, *, org_id: str) -> bool:
    """原型階段是否已結束（旗標是否已設）。"""
    return core_settings.get_setting(conn, FLAG_SETTING, org_id=org_id) is not None


def check_and_flag(conn, *, org_id: str, actual_spend: float, actor: str,
                   cycle_id: str | None = None) -> bool:
    """檔期結算完成時呼叫（app/ads/reading.finalize()）。已經結束過就什麼都不做；
    第一次「結算完成且實際花費 > 0」才設旗標、寫稽核紀錄、進打斷佇列。

    這是全系統唯一會把旗標設成「已結束」的地方，也是判定本身（決策 0037 配套檢查）。
    回傳這次呼叫是不是真的觸發了旗標翻轉，方便呼叫端測試，不影響外部行為。

    org_id（票 03-1）：旗標本身仍是全站單一旗標（不分品牌），但 app_setting／interrupt
    兩張表都是 NOT NULL org_id——呼叫端（app/ads/reading.py）已經有 brand_id，反查
    org_id 傳進來；app.core 不得 import app.brand_intelligence 自己反查（LAYER_ORDER）。
    """
    if has_ended(conn, org_id=org_id):
        return False
    if not actual_spend or actual_spend <= 0:
        return False

    core_settings.set_setting(conn, FLAG_SETTING, now_iso(), org_id=org_id)
    write_audit(
        conn, org_id=org_id, brand_id=None, entity_type="prototype_phase", entity_id="system",
        action="ended", actor=actor,
        after={"actual_spend": actual_spend, "triggered_by_cycle_id": cycle_id,
               "exemptions": EXEMPTIONS},
        reason="第一次用真錢跑完一期（決策 0037 第一節第 1 條）",
    )
    core_interrupts.enqueue(
        conn, org_id=org_id, category="prototype_phase_ended",
        dedupe_key="prototype_phase_ended",
        message=_REMINDER_MESSAGE, brand_id=None,
        action_url="/app/inbox",
    )
    conn.commit()
    return True


def demo() -> None:
    """python -m app.core.prototype_phase — 純函數自檢：EXEMPTIONS 結構完整。"""
    assert len(EXEMPTIONS) == 4
    for exemption in EXEMPTIONS:
        assert exemption["item"] and exemption["status"]
    assert len(_REMINDER_MESSAGE) <= 30
    print("prototype_phase 自檢通過")


if __name__ == "__main__":
    demo()
