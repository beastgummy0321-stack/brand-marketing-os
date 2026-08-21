# -*- coding: utf-8 -*-
"""app/tests/test_ads_checkpoint.py — 生成管線票 9（GitHub issue #19）：期中檢查點＋素材疲勞。

重點：健康檢查模式（第 3／7 天）明文不判勝負——就算故意餵會被判成「可以加碼」的漂亮數字，
回傳結果也不能出現任何贏／輸等級的欄位。疲勞警示讀 app.core.rule_cards 的示範規則卡門檻，
不是另外拍腦袋一個常數。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_checkpoint_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import checkpoint  # noqa: E402
from app.ads import onboarding  # noqa: E402
from app.ads import performance as ads_performance  # noqa: E402
from app.ads import reading  # noqa: E402
from app.core import interrupts as core_interrupts  # noqa: E402
from app.core import rule_cards  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402



def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"

# 有花費、有轉換、有營收，經 reading.judge() 會判成「可以考慮加碼」的漂亮數字——
# 拿來確保健康檢查模式就算餵這種數字，也不會偷跑出勝負結論。
GOOD_CSV = (
    "報告開始,花費金額,曝光次數,連結點擊次數,購買次數,購買轉換價值\n"
    "2026-08-01,10000,20000,400,10,80000\n"
)
FATIGUE_CSV = (
    "報告開始,花費金額,曝光次數,連結點擊次數,頻率\n"
    "2026-08-01,3000,15000,300,5.0\n"
)


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        self.product = bi_repo.create_product(main.conn, self.bid, name="虛構濾掛組",
                                              actor=ACTOR)["id"]
        bi_repo.save_product_economics(main.conn, self.bid, self.product, selling_price=1000,
                                       unit_variable_cost=400, currency="TWD",
                                       confirmed_by=ACTOR, actor=ACTOR)

    def _live_cycle(self, start_offset_days=-10):
        resp = self.client.post(f"/api/campaigns/{self.bid}",
                                json={"product_ids": [self.product], "budget": 10000,
                                      "objective": "sales"})
        cycle_id = resp.json()["cycle_id"]
        start = (date.today() + timedelta(days=start_offset_days)).isoformat()
        end = (date.today() + timedelta(days=start_offset_days + 13)).isoformat()
        main.conn.execute(
            "UPDATE campaign_cycle SET status = 'LIVE', start_date = ?, end_date = ?"
            " WHERE id = ?", (start, end, cycle_id))
        main.conn.commit()
        onboarding.create_reminders(main.conn, self.bid, cycle_id)
        return cycle_id


class HealthCheckModeTest(_Base):
    """驗收：健康檢查模式不輸出勝負等級。"""

    def test_no_data_is_honest_not_a_guess(self):
        cycle_id = self._live_cycle(start_offset_days=-4)
        result = checkpoint.run(main.conn, self.bid, cycle_id, "day3", actor=ACTOR)
        self.assertFalse(result["data_sufficient"])
        self.assertIn("先匯入 CSV", result["learning_note"])
        self.assertIsNone(result["spend_ok"])
        self.assertNotIn("status", result)

    def test_great_numbers_still_produce_no_verdict(self):
        """故意餵會被判成『可以加碼』的漂亮數字：健康檢查模式仍然不能出現任何贏輸等級。"""
        cycle_id = self._live_cycle(start_offset_days=-8)
        result = checkpoint.run(main.conn, self.bid, cycle_id, "day7", actor=ACTOR,
                                csv_text=GOOD_CSV)
        self.assertTrue(result["data_sufficient"])
        self.assertTrue(result["spend_ok"])
        self.assertTrue(result["learning_normal"])
        # 硬規則：不管數字多漂亮，回傳裡都不能出現「贏／輸」等級的欄位或用字。
        self.assertNotIn("status", result)
        self.assertNotIn("roas", result)
        dump = str(result)
        for verdict_word in reading.STATUS_LABELS.values():
            self.assertNotIn(verdict_word, dump)

        # 同一組漂亮數字如果真的拿去給成效判讀（不是健康檢查），會判成「可以考慮加碼」——
        # 證明不是「數字本身判不出來」，而是健康檢查模式刻意不呼叫那條判讀路徑。
        ok, _ = reading.run(main.conn, self.bid, cycle_id, ACTOR)
        self.assertTrue(ok)
        loaded = reading.load(main.conn, self.bid, cycle_id)
        self.assertEqual(loaded["cycle"]["status"], "scale_candidate")

    def test_day3_has_no_fatigue_field(self):
        """第 3 天只驗學習期正常＋錢有在花，不該有素材疲勞欄位。"""
        cycle_id = self._live_cycle(start_offset_days=-4)
        result = checkpoint.run(main.conn, self.bid, cycle_id, "day3", actor=ACTOR,
                                csv_text=GOOD_CSV)
        self.assertIsNone(result["fatigue"])

    def test_zero_spend_is_flagged_not_silently_ok(self):
        cycle_id = self._live_cycle(start_offset_days=-4)
        result = checkpoint.run(main.conn, self.bid, cycle_id, "day3", actor=ACTOR,
                                csv_text="報告開始,花費金額\n2026-08-01,0\n")
        self.assertFalse(result["spend_ok"])
        self.assertIn("不正常", result["spend_note"])

    def test_missing_reach_column_is_honest_not_a_guess(self):
        """觸及是曝光期主指標，第 3 天缺欄不擋匯入，但要有針對性的人話提醒
        （比照 day7 缺頻率欄的既有寫法，票 03-add-reach-metric）。"""
        cycle_id = self._live_cycle(start_offset_days=-4)
        result = checkpoint.run(main.conn, self.bid, cycle_id, "day3", actor=ACTOR,
                                csv_text=GOOD_CSV)  # 沒有觸及欄
        self.assertIsNone(result["reach"]["reach"])
        self.assertIn("沒有帶", result["reach"]["note"])

    def test_reach_present_is_reported(self):
        cycle_id = self._live_cycle(start_offset_days=-4)
        csv_text = "報告開始,花費金額,觸及人數\n2026-08-01,3000,7000\n"
        result = checkpoint.run(main.conn, self.bid, cycle_id, "day3", actor=ACTOR,
                                csv_text=csv_text)
        self.assertEqual(result["reach"]["reach"], 7000)

    def test_day7_has_no_reach_field(self):
        """觸及是第 3 天（曝光期）看的，第 7 天不該有這個欄位，跟 day3 沒有疲勞欄位對稱。"""
        cycle_id = self._live_cycle(start_offset_days=-8)
        result = checkpoint.run(main.conn, self.bid, cycle_id, "day7", actor=ACTOR,
                                csv_text=GOOD_CSV)
        self.assertIsNone(result["reach"])


class FatigueTest(_Base):
    """驗收：疲勞警示讀規則卡（票 2 示範門檻），不是另外拍一個常數。"""

    def test_day7_fatigue_reads_the_rule_card_threshold(self):
        cycle_id = self._live_cycle(start_offset_days=-8)
        result = checkpoint.run(main.conn, self.bid, cycle_id, "day7", actor=ACTOR,
                                csv_text=FATIGUE_CSV)
        # 頻率 5.0，冷受眾開發的危險門檻是 4.0（app.core.rule_cards CARDS['ad_creative_fatigue']）
        self.assertEqual(result["fatigue"]["status"], "danger")
        self.assertEqual(result["fatigue"]["status_label"],
                         rule_cards.FATIGUE_STATUS_LABELS["danger"])
        expected = rule_cards.classify_ad_frequency(main.conn, self.bid, "cold", 5.0)
        self.assertEqual(result["fatigue"]["status"], expected)

    def test_missing_frequency_column_is_honest_not_a_guess(self):
        cycle_id = self._live_cycle(start_offset_days=-8)
        result = checkpoint.run(main.conn, self.bid, cycle_id, "day7", actor=ACTOR,
                                csv_text=GOOD_CSV)  # 沒有頻率欄
        self.assertIsNone(result["fatigue"]["frequency"])
        self.assertIn("沒有帶", result["fatigue"]["note"])


class FlowTest(_Base):
    """驗收：提醒卡觸發 → 當場匯入 CSV → 立即跑判讀一條龍可走通。"""

    def test_full_flow_import_then_checkpoint(self):
        cycle_id = self._live_cycle(start_offset_days=-8)
        page = self.client.get(f"/api/campaigns/{self.bid}/{cycle_id}/checkpoint/day7")
        self.assertEqual(page.status_code, 200)

        result = checkpoint.run(main.conn, self.bid, cycle_id, "day7", actor=ACTOR,
                                csv_text=FATIGUE_CSV)
        self.assertEqual(result["import_errors"], [])

        latest = self.client.get(
            f"/api/campaigns/{self.bid}/{cycle_id}/checkpoint/day7").json()["data"]
        self.assertIn("危險", latest["fatigue"]["status_label"])

        rows = checkpoint.list_checkpoints(main.conn, self.bid, cycle_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "day7")

    def test_bad_csv_shows_the_honest_error(self):
        cycle_id = self._live_cycle(start_offset_days=-4)
        result = checkpoint.run(main.conn, self.bid, cycle_id, "day3", actor=ACTOR,
                                csv_text="not,a,valid,performance,file\n1,2,3,4,5\n")
        self.assertIn("花費", result["import_errors"][0])

    def test_reminder_links_into_checkpoint_page(self):
        cycle_id = self._live_cycle(start_offset_days=-4)
        page = self.client.get(f"/brands/{self.bid}/ads/{cycle_id}")
        self.assertIn(f"/app/brands/{self.bid}/campaigns/{cycle_id}", page.text)



class EventBasedCheckpointTest(_Base):
    """票 #38，決策 0025 審查補遺第 4 點：期中檢查點是事件不是死線——
    使用者過時才來，直接併入期末判讀，不用補做。"""

    def _run_final_reading(self, cycle_id):
        ads_performance.import_manual(main.conn, self.bid, cycle_id,
                                      {"spend": 10000, "impressions": 20000, "clicks": 400,
                                       "conversions": 10, "revenue": 40000}, actor=ACTOR)
        ok, err = reading.run(main.conn, self.bid, cycle_id, ACTOR)
        self.assertTrue(ok, err)

    def test_checkpoint_merges_into_final_once_cycle_is_no_longer_live(self):
        cycle_id = self._live_cycle(start_offset_days=-8)
        self._run_final_reading(cycle_id)  # 期末判讀先跑過，等於使用者這期直接補到期末

        result = checkpoint.run(main.conn, self.bid, cycle_id, "day3", actor=ACTOR)
        self.assertTrue(result.get("merged_into_final"))
        self.assertNotIn("status", result)  # 仍然不能出現贏／輸等級的欄位
        self.assertEqual(checkpoint.list_checkpoints(main.conn, self.bid, cycle_id), [])

    def test_stale_day3_reminder_is_resolved_once_final_reading_runs(self):
        cycle_id = self._live_cycle(start_offset_days=-8)
        due = onboarding.due_reminders(main.conn, self.bid)
        day3_id = next(d["id"] for d in due if d["kind"] == "day3_look_dont_touch")

        self._run_final_reading(cycle_id)

        remaining_ids = [d["id"] for d in onboarding.due_reminders(main.conn, self.bid)]
        self.assertNotIn(day3_id, remaining_ids)
        # 不只是「篩掉不顯示」，是整條佇列紀錄真的被結掉（inbox／頁頂當前一件也不會再看到）。
        raw = [r["id"] for r in core_interrupts.list_open(main.conn, brand_id=self.bid,
                                                           category="cycle_reminder")]
        self.assertNotIn(day3_id, raw)
        row = main.conn.execute("SELECT status FROM interrupt WHERE id = ?",
                                (day3_id,)).fetchone()
        self.assertEqual(row["status"], "resolved")

    def test_page_hides_the_import_form_once_merged_into_final(self):
        cycle_id = self._live_cycle(start_offset_days=-8)
        self._run_final_reading(cycle_id)
        page = self.client.get(f"/brands/{self.bid}/ads/{cycle_id}/checkpoint/day3")
        self.assertIn("併入期末結論", page.text)

    def test_direct_post_after_merge_shows_a_friendly_message(self):
        cycle_id = self._live_cycle(start_offset_days=-8)
        self._run_final_reading(cycle_id)
        resp = self.client.post(f"/brands/{self.bid}/ads/{cycle_id}/checkpoint/day7",
                                data={"csv_text": GOOD_CSV}, follow_redirects=True)
        self.assertIn("不用再補做", resp.text)


class ArchiveDeleteTest(_Base):
    """驗收：檢查點紀錄落庫、附封存刪除（決策 0023 第 8 條）。"""

    def test_archive_then_restore(self):
        cycle_id = self._live_cycle(start_offset_days=-4)
        result = checkpoint.run(main.conn, self.bid, cycle_id, "day3", actor=ACTOR,
                                csv_text=GOOD_CSV)
        checkpoint.set_status(main.conn, self.bid, result["id"], status="archived", actor=ACTOR)
        active = checkpoint.list_checkpoints(main.conn, self.bid, cycle_id)
        self.assertTrue(all(r["status"] == "archived" for r in active))

        checkpoint.set_status(main.conn, self.bid, result["id"], status="active", actor=ACTOR)
        active = checkpoint.list_checkpoints(main.conn, self.bid, cycle_id)
        self.assertEqual(active[0]["status"], "active")

    def test_delete_removes_the_row(self):
        cycle_id = self._live_cycle(start_offset_days=-4)
        result = checkpoint.run(main.conn, self.bid, cycle_id, "day3", actor=ACTOR,
                                csv_text=GOOD_CSV)
        checkpoint.delete(main.conn, self.bid, result["id"], actor=ACTOR)
        self.assertEqual(checkpoint.list_checkpoints(main.conn, self.bid, cycle_id), [])

    def test_archive_and_delete_routes(self):
        cycle_id = self._live_cycle(start_offset_days=-4)
        result = checkpoint.run(main.conn, self.bid, cycle_id, "day3", actor=ACTOR,
                                csv_text=GOOD_CSV)

        resp = self.client.post(f"/brands/{self.bid}/ads/checkpoints/{result['id']}/archive",
                                follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(
            checkpoint.list_checkpoints(main.conn, self.bid, cycle_id)[0]["status"], "archived")

        resp = self.client.post(f"/brands/{self.bid}/ads/checkpoints/{result['id']}/delete",
                                follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(checkpoint.list_checkpoints(main.conn, self.bid, cycle_id), [])


if __name__ == "__main__":
    unittest.main()
