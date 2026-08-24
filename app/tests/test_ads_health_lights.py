# -*- coding: utf-8 -*-
"""app/tests/test_ads_health_lights.py — 檔期健康燈號（B4R 收尾包項目 2／3）。

燈號黃燈門檻改走 rule_cards 後的最小驗證：四盞燈算得出來、規則卡調整後燈號真的
跟著變（不是還在讀模組層寫死的常數）。品牌與產品一律虛構。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_health_lights_")

import app.main as main  # noqa: E402
from app.ads import health_lights  # noqa: E402
from app.ads import performance as ads_performance  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import rule_cards  # noqa: E402



def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"


class HealthLightsTest(unittest.TestCase):
    def setUp(self):
        self.bid = bi_repo.create_brand(
            main.conn, name="虛構晨露茶行", client_name="測試客戶", actor=ACTOR)["id"]

    def _cycle(self, *, start_offset_days: int, product_ids=None) -> dict:
        start = date.today() - timedelta(days=start_offset_days)
        return ads_repo.create_cycle(
            main.conn, self.bid, product_ids=product_ids or [], pain_value=6000,
            objective="sales", actor=ACTOR, start_date=start.isoformat(), duration_days=40)

    def test_compute_returns_four_lights_without_data(self):
        """檔期剛開跑、什麼成效資料都還沒進來：四盞燈都該誠實回「算不出來」，
        不是硬猜一個顏色（鐵則 16）。"""
        cycle = self._cycle(start_offset_days=0)
        lights = health_lights.compute(main.conn, self.bid, cycle["id"])
        self.assertEqual(set(lights), {"spend_rate", "cpa", "roas", "fatigue"})
        for key, light in lights.items():
            self.assertEqual(light["status"], "insufficient", key)

    def test_spend_rate_yellow_ratio_rule_card_changes_the_light(self):
        cycle = self._cycle(start_offset_days=20)
        start = date.fromisoformat(cycle["start_date"])
        end = date.fromisoformat(cycle["end_date"])
        total_days = (end - start).days + 1
        elapsed_days = (date.today() - start).days + 1
        time_progress = elapsed_days / total_days
        # 花費進度比時間進度快 5 個百分點：預設步調門檻 0.15，遠沒超過，pacing 判定仍是 normal。
        spend = round(cycle["budget"] * (time_progress + 0.05), 2)
        ads_performance.import_manual(main.conn, self.bid, cycle["id"],
                                      {"spend": spend, "date_start": start.isoformat()},
                                      actor=ACTOR)

        default_light = health_lights.compute(main.conn, self.bid, cycle["id"])["spend_rate"]
        self.assertEqual(default_light["status"], "green")  # 預設比例 0.6：0.05 <= 0.15*0.6=0.09

        rule_cards.set_value(main.conn, self.bid, "health_lights", "spend_yellow_ratio", 0.1, ACTOR)
        changed_light = health_lights.compute(main.conn, self.bid, cycle["id"])["spend_rate"]
        self.assertEqual(changed_light["status"], "yellow")  # 0.15*0.1=0.015，0.05 超過了

    def test_cpa_yellow_multiplier_rule_card_changes_the_light(self):
        product_id = bi_repo.create_product(main.conn, self.bid, name="虛構茉莉綠茶", actor=ACTOR)["id"]
        bi_repo.save_product_economics(main.conn, self.bid, product_id, actor=ACTOR,
                                       selling_price=500, currency="TWD", confirmed_by=ACTOR,
                                       unit_variable_cost=300)  # 毛利 200 → 打平 CPA=200
        cycle = self._cycle(start_offset_days=20, product_ids=[product_id])
        ads_performance.import_manual(
            main.conn, self.bid, cycle["id"],
            {"spend": 1000, "conversions": 4, "date_start": cycle["start_date"]}, actor=ACTOR)
        # 實際 CPA = 1000/4 = 250，目標 200

        default_light = health_lights.compute(main.conn, self.bid, cycle["id"])["cpa"]
        self.assertEqual(default_light["status"], "yellow")  # 預設倍率 1.3：250 <= 200*1.3=260

        rule_cards.set_value(main.conn, self.bid, "health_lights", "cpa_yellow_multiplier", 1.1, ACTOR)
        changed_light = health_lights.compute(main.conn, self.bid, cycle["id"])["cpa"]
        self.assertEqual(changed_light["status"], "red")  # 200*1.1=220，250 超過了

    def test_roas_yellow_multiplier_rule_card_changes_the_light(self):
        product_id = bi_repo.create_product(main.conn, self.bid, name="虛構冷萃茶", actor=ACTOR)["id"]
        bi_repo.save_product_economics(main.conn, self.bid, product_id, actor=ACTOR,
                                       selling_price=500, currency="TWD", confirmed_by=ACTOR,
                                       unit_variable_cost=300)  # 打平投報率 500/200=2.5
        cycle = self._cycle(start_offset_days=20, product_ids=[product_id])
        ads_performance.import_manual(
            main.conn, self.bid, cycle["id"],
            {"spend": 1000, "revenue": 2000, "date_start": cycle["start_date"]}, actor=ACTOR)
        # 實際 ROAS = 2000/1000 = 2.0，打平線 2.5

        default_light = health_lights.compute(main.conn, self.bid, cycle["id"])["roas"]
        self.assertEqual(default_light["status"], "yellow")  # 預設倍率 0.8：2.0 >= 2.5*0.8=2.0

        rule_cards.set_value(main.conn, self.bid, "health_lights", "roas_yellow_multiplier", 0.9, ACTOR)
        changed_light = health_lights.compute(main.conn, self.bid, cycle["id"])["roas"]
        self.assertEqual(changed_light["status"], "red")  # 2.5*0.9=2.25，2.0 沒到

    def test_fatigue_light_note_is_a_full_sentence_not_just_the_two_char_label(self):
        """票 R1-live-reading-output done-check 4：疲勞燈以前 note 直接回
        `FATIGUE_STATUS_LABELS[status]`，只有「警示」／「危險」兩個字，跟其他三盞燈
        （都是帶實際數字的整句白話）不同款。"""
        cycle = self._cycle(start_offset_days=20)
        csv_text = "花費金額,廣告名稱,頻率\n1000,虛構廣告,5.0\n"
        ads_performance.import_csv(main.conn, self.bid, cycle["id"], csv_text, actor=ACTOR)

        light = health_lights.compute(main.conn, self.bid, cycle["id"])["fatigue"]

        self.assertEqual(light["status"], "red")  # cold_danger 預設 3.5，5.0 超過
        self.assertNotEqual(light["note"], "危險")  # 不能只剩兩個字
        self.assertIn("5.00", light["note"])  # 整句要帶實際頻率數字，不是空泛形容詞


if __name__ == "__main__":
    unittest.main()
