# -*- coding: utf-8 -*-
"""app/tests/test_ads_boot_catchup.py — 票 F6：開機自動啟動的「補跑」與「不當機」。

不啟動真的 server（見 CLAUDE.md／F6 票的硬限制：`_auto_sync_if_due` 一旦在活著的
process 裡跑，會打外部 API、也會結算 data/app.db 裡的 B1 演練檔期）。全程只呼叫
`app.main` 裡的觸發函式本身，用 TestClient 不進 context manager那條既有防線
（見 test_ads_auto_sync.py AutoSyncScheduleSafetyTest）保證 startup 事件不會被
意外碰到。

三張測試對應 F6 的兩個缺口：
1. 「process 沒人啟動」不是這裡測的（那是 schtasks／launcher 那半，人工驗證）。
2. 「第一拍太晚」——`_register_auto_sync_schedule` 其實從票 07 一開始就已經在背景
   執行緒 `time.sleep()` 之前先同步呼叫過一次 `_auto_sync_if_due()`，這條已經是對的
   （`BootCatchupTimingTest` 只是釘住這個事實，不是修出來的）。
3. 但那次同步呼叫沒有包 try/except——補跑本身若丟例外（外部 API 掛點、資料庫忙碌），
   會讓 FastAPI startup 事件失敗，等於開機直接不起來，比「晚一點結算」嚴重得多
   （集裝箱憲章第 5 節：錯誤不穿牆）。`StartupCatchupSafetyTest` 是這張票真正的
   RED→GREEN：修之前這支測試會讓例外整個穿出 `_register_auto_sync_schedule`。
"""

import atexit
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_boot_catchup_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import onboarding  # noqa: E402
from app.ads import performance as perf  # noqa: E402
from app.ads import reading  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"


def _fake(text: str) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=300, output_tokens=150),
                            stop_reason="end_turn")


class OverdueSettlementCatchupTest(unittest.TestCase):
    """完成檢查 1：檔期過了 end_date+14、也有一張還開著的 final_settlement 提醒，
    呼叫觸發函式本身（不是活的 server）就能把它結掉。"""

    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構補跑咖啡", client_name=None,
                                          actor=ACTOR)
        self.bid = self.brand["id"]
        self.product = bi_repo.create_product(main.conn, self.bid, name="虛構濾掛組",
                                              actor=ACTOR)["id"]
        bi_repo.save_product_economics(main.conn, self.bid, self.product, selling_price=1000,
                                       unit_variable_cost=400, currency="TWD",
                                       confirmed_by=ACTOR, actor=ACTOR)
        resp = self.client.post(f"/api/campaigns/{self.bid}",
                                json={"product_ids": [self.product], "budget": 10000,
                                      "objective": "sales"})
        self.cycle_id = resp.json()["cycle_id"]
        self._orig_provider = reading.PROVIDER
        reading.PROVIDER = FakeProvider(response=_fake('{"text": "測試判讀說明"}'))
        # 檔期結束日訂在「今天往前推 14 天」——final_settlement 的到期日正好是今天
        # （onboarding.py：offset_from_end_days=14），比照 test_ads_onboarding.py
        # ReminderTest._live_cycle 同一套「往回訂日期」寫法。
        end = date.today() - timedelta(days=14)
        start = end - timedelta(days=29)
        main.conn.execute(
            "UPDATE campaign_cycle SET status = 'LIVE', start_date = ?, end_date = ?"
            " WHERE id = ?", (start.isoformat(), end.isoformat(), self.cycle_id))
        main.conn.commit()
        onboarding.create_reminders(main.conn, self.bid, self.cycle_id)
        perf.import_manual(main.conn, self.bid, self.cycle_id,
                           {"spend": 10000, "impressions": 20000, "clicks": 400,
                            "conversions": 10, "revenue": 40000}, actor=ACTOR)
        main._last_auto_sync_check = None  # 強制視為「該檢查了」，不受其他測試殘留影響

    def tearDown(self):
        reading.PROVIDER = self._orig_provider

    def _open_final_settlement(self):
        return main.conn.execute(
            "SELECT status FROM interrupt WHERE campaign_cycle_id = ? AND kind = 'final_settlement'",
            (self.cycle_id,)).fetchone()

    def test_invoking_trigger_function_settles_overdue_cycle(self):
        reminder_before = self._open_final_settlement()
        self.assertEqual(reminder_before["status"], "open")
        cycle_before = ads_repo.get_cycle(main.conn, self.bid, self.cycle_id)
        self.assertNotEqual(cycle_before["status"], "CLOSED")

        main._auto_sync_if_due()  # 這就是 F6 票鏈路的觸發函式本身，不是活的 server

        cycle_after = ads_repo.get_cycle(main.conn, self.bid, self.cycle_id)
        self.assertEqual(cycle_after["status"], "CLOSED")
        reminder_after = self._open_final_settlement()
        self.assertEqual(reminder_after["status"], "resolved")


class BootCatchupTimingTest(unittest.TestCase):
    """完成檢查 2：補跑要在 process 一起來就跑，不必等第一個 poll interval。

    釘住既有正確行為（`_register_auto_sync_schedule` 早在票 07 就是「先同步呼叫一次，
    再把背景迴圈丟給執行緒」的順序），順便交代清楚——F6 票原始 handoff 誤判這裡有缺口，
    重新核對程式碼後這條已經是對的，不需要改。背景迴圈本體用 mock 換掉，測試不必真的
    等 3600 秒。"""

    def test_catchup_fires_synchronously_before_the_background_loop_is_started(self):
        with (mock.patch.object(main, "_auto_sync_if_due") as due_mock,
              mock.patch.object(main, "_weekly_engine_if_due") as weekly_mock,
              mock.patch.object(main, "_auto_sync_loop")):
            main._register_auto_sync_schedule()
        due_mock.assert_called_once_with()
        weekly_mock.assert_called_once_with()


class StartupCatchupSafetyTest(unittest.TestCase):
    """這張票真正要修的地方：補跑丟例外不能把開機一起帶垮（集裝箱憲章第 5 節，
    錯誤不穿牆）。修之前這裡會讓 RuntimeError 直接穿出 `_register_auto_sync_schedule`，
    等於 FastAPI startup 事件失敗、開機失敗——比「晚一點結算」嚴重得多。"""

    def test_register_auto_sync_schedule_survives_catchup_exception(self):
        with (mock.patch.object(main, "_auto_sync_if_due", side_effect=RuntimeError("boom")),
              mock.patch.object(main, "_weekly_engine_if_due") as weekly_mock,
              mock.patch.object(main, "_auto_sync_loop")):
            main._register_auto_sync_schedule()  # 不該把整個 app 帶垮
        weekly_mock.assert_called_once_with()  # 補跑掛了，週判讀跟背景迴圈還是要照常掛上去


if __name__ == "__main__":
    unittest.main()
