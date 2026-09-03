"""app/tests/test_schedule_period.py — 票 T2b（ADR 0053）：檔期的結算端點。

只寫這四類（CLAUDE.md，票 T2b done-check 3 明講的四個）：
  money：兩個重疊檔期（30 天／5 天），短的整段吃走重疊的日子，兩邊結算金額加總等於
         這整段日子真正花掉的錢（ADR 0053 決策 4 的粗顆粒版本）。
  money：重新結算把舊的三個數字寫進 audit_log，新舊快照不同。
  tenant isolation：結算端點帶另一個組織的檔期 id 一律 404，且不寫任何東西。
  API contract：GET 沒有檔期回 `period: null`，有檔期回 ticket 講的那組字面鍵。

不走「填表單出方案→展開→核准」整條鏈——那條鏈本身已經在 test_schedule.py／
test_approval.py 測過；這裡直接寫 `campaign_period`／`meta_entity_spend`／
`channel_revenue` 三張表造資料，只測結算端點自己的算法與租戶界線。只用直接寫表，不打
真實網路請求。

票 T3e（ADR 0055 §11）沒有列這個檔案，但它的花費改讀 `level="adset"`（ticket §5）動到
`_seed_spend()` 這一個字——原本寫死 `level="campaign"` 的花費列在新的查詢層下讀不到，
呼叫 `_seed_spend()` 的兩支 money 測試（`SettlementOwnershipSumTest`、
`ResettlementAuditTest`）會全部靜靜地變成「這期花了 0 元」（另外兩支不呼叫
`_seed_spend()`，不受影響）。這裡沒有綁定、沒有 membership，所以改的只是花費列寫在
哪一層，測的規則（品牌層擁有者、並列平分、重新結算）一個字都沒變——跟 T3b／T3c 兩張票
都各自「多動了一個 ticket 沒列的檔案」同一個模式（見 T3b 的 commit message）。
"""

import unittest
import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient

import app.main as main
import app.schedule as schedule_module
import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.meta import repository as meta_repo

ACTOR = "測試員"


def _daterange(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


class _PeriodTestBase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        schedule_module.register_tasks()
        self.brand = bi_repo.create_brand(
            web.conn, org_id=coredb.DEV_ORG_ID, name="測試品牌：檔期結算",
            client_name=None, actor=ACTOR,
        )
        web.conn.commit()

    def _insert_period(self, *, org_id: str, brand_id: str, start: date, end: date,
                        status: str = "running") -> str:
        period_id = coredb.new_id("cpd")
        web.conn.execute(
            "INSERT INTO campaign_period (id, org_id, brand_id, name, start_date, end_date,"
            " status, daily_budget, currency) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'TWD')",
            (period_id, org_id, brand_id, f"{start.isoformat()} ~ {end.isoformat()}",
             start, end, status, 1000.0),
        )
        web.conn.commit()
        return period_id

    def _bind_account(self, org_id: str, brand_id: str) -> str:
        meta_repo.save_token(web.conn, org_id, "tok")
        external_id = f"act_{uuid.uuid4().hex[:10]}"
        meta_repo.upsert_accounts(web.conn, org_id, [
            {"account_id": external_id, "name": "測試帳號", "currency": "TWD"},
        ])
        account_id = web.conn.execute(
            "SELECT id FROM meta_ad_account WHERE account_id = %s", (external_id,)
        ).fetchone()["id"]
        meta_repo.bind(web.conn, org_id, brand_id, account_id)
        web.conn.commit()
        return account_id

    def _seed_spend(self, org_id: str, account_id: str, day: date, spend: float,
                     campaign_id: str = "camp-1") -> None:
        # 票 T3e：`compute_money()` 的花費從 `level="campaign"` 換成 `level="adset"`
        # （ticket §5）——這裡沒有任何綁定／membership，所以每一筆花費在這支測試裡都是
        # 「未登記」，照舊落到品牌層的檔期擁有者（ADR 0055 §11 的既有行為，這支測試守的
        # 就是那條規則本身，不是綁定），只是資料現在要寫在正確的層才讀得到。
        meta_repo.upsert_entity_spend(web.conn, org_id, account_id, [
            {"level": "adset", "entity_id": campaign_id, "entity_name": "廣告組合一",
             "campaign_id": campaign_id, "adset_id": campaign_id, "ad_id": None,
             "spend_date": day, "spend": spend, "impressions": 10, "clicks": 1, "roas": None,
             "actions": None, "action_values": None,
             "attribution_window": "7d_click,1d_view"},
        ])
        web.conn.commit()

    def _make_org(self, suffix: str) -> str:
        org_id = f"org_period_test_{suffix}"
        web.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (org_id, org_id),
        )
        web.conn.commit()
        return org_id

    def _settle(self, brand_id: str, period_id: str):
        return self.client.post(
            f"/api/schedule/brands/{brand_id}/periods/{period_id}/settle", json={}
        )


class SettlementOwnershipSumTest(_PeriodTestBase):
    """money：30 天跟 5 天兩個檔期重疊 5 天——短的整段吃走重疊的日子，兩邊結算金額加總
    等於這整段日子真正花掉的錢，且 5 天檔期擁有全部 5 個重疊日（ADR 0053 決策 4）；同一個
    測試再加一段天數並列（三個 1 天檔期疊同一天）——並列平分那一天的花費，三邊加總精確
    等於那一天真正花掉的錢，且沒有人是贏家全拿的 0 或 100。"""

    def test_shorter_period_owns_the_overlap_and_totals_reconcile(self):
        org_id = coredb.DEV_ORG_ID
        account_id = self._bind_account(org_id, self.brand["id"])
        start = date(2026, 6, 1)
        long_end = date(2026, 6, 30)       # 30 天：6/1～6/30
        short_start = date(2026, 6, 21)    # 5 天：6/21～6/25，疊在長檔期尾端
        short_end = date(2026, 6, 25)

        for i, day in enumerate(_daterange(start, long_end)):
            self._seed_spend(org_id, account_id, day, spend=100.0 + i)

        long_id = self._insert_period(
            org_id=org_id, brand_id=self.brand["id"], start=start, end=long_end,
        )
        short_id = self._insert_period(
            org_id=org_id, brand_id=self.brand["id"], start=short_start, end=short_end,
        )

        resp_long = self._settle(self.brand["id"], long_id)
        self.assertEqual(resp_long.status_code, 200, resp_long.text)
        resp_short = self._settle(self.brand["id"], short_id)
        self.assertEqual(resp_short.status_code, 200, resp_short.text)

        long_spend = float(web.conn.execute(
            "SELECT settled_spend FROM campaign_period WHERE id = %s", (long_id,)
        ).fetchone()["settled_spend"])
        short_spend = float(web.conn.execute(
            "SELECT settled_spend FROM campaign_period WHERE id = %s", (short_id,)
        ).fetchone()["settled_spend"])

        total_spend = sum(100.0 + i for i in range(30))
        self.assertAlmostEqual(long_spend + short_spend, total_spend, places=2)

        # 短檔期整段五天都歸它自己，不是被長檔期分走一部分（index 20..24 = 6/21..6/25）
        short_only_spend = sum(100.0 + i for i in range(20, 25))
        self.assertAlmostEqual(short_spend, short_only_spend, places=2)

        # 並列（三個檔期同樣長——都是同一天，重疊在同一天）：ADR 0053 決策 4「並列 →
        # 平分」，不是贏家全拿。100 元除以 3 除不盡，是 naive `/ n` 會出錯、
        # `largest_remainder_allocation()` 不會出錯的輸入。
        tie_day = date(2026, 7, 1)
        self._seed_spend(org_id, account_id, tie_day, spend=100.0, campaign_id="camp-tie")
        tie_ids = [
            self._insert_period(
                org_id=org_id, brand_id=self.brand["id"], start=tie_day, end=tie_day,
            )
            for _ in range(3)
        ]
        tie_spends = []
        for pid in tie_ids:
            resp = self._settle(self.brand["id"], pid)
            self.assertEqual(resp.status_code, 200, resp.text)
            tie_spends.append(float(web.conn.execute(
                "SELECT settled_spend FROM campaign_period WHERE id = %s", (pid,)
            ).fetchone()["settled_spend"]))

        self.assertEqual(sum(tie_spends), 100.0)
        # 平分，不是贏家全拿：三份都落在 33.33～33.34 之間，沒有人是 0，也沒有人是 100。
        for s in tie_spends:
            self.assertTrue(33.33 <= s <= 33.34, tie_spends)


class ResettlementAuditTest(_PeriodTestBase):
    """money：重新結算之前，舊的快照先進 audit_log；新快照跟舊的不一樣（晚到的錢真的
    被抓到，不是憑空重複同一個數字）。"""

    def test_resettle_writes_previous_snapshot_to_audit_log_and_snapshot_changes(self):
        org_id = coredb.DEV_ORG_ID
        account_id = self._bind_account(org_id, self.brand["id"])
        start = date(2026, 5, 1)
        end = date(2026, 5, 5)
        self._seed_spend(org_id, account_id, start, spend=1000.0)
        period_id = self._insert_period(
            org_id=org_id, brand_id=self.brand["id"], start=start, end=end,
        )

        resp1 = self._settle(self.brand["id"], period_id)
        self.assertEqual(resp1.status_code, 200, resp1.text)
        first_spend = float(web.conn.execute(
            "SELECT settled_spend FROM campaign_period WHERE id = %s", (period_id,)
        ).fetchone()["settled_spend"])

        # 晚到的錢：結算之後又補了一筆花費。
        self._seed_spend(org_id, account_id, start + timedelta(days=1), 500.0,
                          campaign_id="camp-2")

        resp2 = self._settle(self.brand["id"], period_id)
        self.assertEqual(resp2.status_code, 200, resp2.text)
        second_spend = float(web.conn.execute(
            "SELECT settled_spend FROM campaign_period WHERE id = %s", (period_id,)
        ).fetchone()["settled_spend"])

        self.assertNotEqual(first_spend, second_spend)

        audit_rows = list(web.conn.execute(
            "SELECT before_json FROM audit_log WHERE entity_type = 'campaign_period'"
            " AND entity_id = %s ORDER BY created_at", (period_id,),
        ))
        self.assertEqual(len(audit_rows), 1)
        self.assertAlmostEqual(float(audit_rows[0]["before_json"]["settled_spend"]), first_spend)


class SettleTenantIsolationTest(_PeriodTestBase):
    """tenant isolation：`brand_id` 是呼叫端自己組織的品牌（`require_brand` 過得了），
    但 `period_id` 是另一個組織的檔期——結算端點自己的 WHERE 必須擋下來，一律 404，
    且不寫任何東西（既不落地結算數字，也不寫 audit_log）。"""

    def test_another_orgs_period_id_is_404_and_writes_nothing(self):
        org_a = self._make_org("settle-isolation-a")
        period_id = self._insert_period(
            org_id=org_a, brand_id=self.brand["id"],
            start=date(2026, 4, 1), end=date(2026, 4, 5),
        )

        resp = self._settle(self.brand["id"], period_id)
        self.assertEqual(resp.status_code, 404)

        row = web.conn.execute(
            "SELECT settled_at FROM campaign_period WHERE id = %s", (period_id,)
        ).fetchone()
        self.assertIsNone(row["settled_at"])
        self.assertEqual(list(web.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'campaign_period' AND entity_id = %s",
            (period_id,),
        )), [])


class PeriodApiContractTest(_PeriodTestBase):
    """API contract：沒有檔期回 `period: null`；有檔期回 ticket 講的那組字面鍵，
    結算之後 `settled` 也是那組字面鍵。"""

    def test_get_returns_null_then_the_literal_key_set_once_settled(self):
        resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()["period"])

        period_id = self._insert_period(
            org_id=coredb.DEV_ORG_ID, brand_id=self.brand["id"],
            start=date(2026, 1, 1), end=date(2026, 1, 5),
        )
        resp = self.client.get(f"/api/schedule/brands/{self.brand['id']}")
        self.assertEqual(resp.status_code, 200)
        period = resp.json()["period"]
        self.assertEqual(period["id"], period_id)
        self.assertEqual(
            set(period.keys()),
            {"id", "name", "status", "start_date", "end_date", "daily_budget", "currency",
             "settle_advice_date", "settled"},
        )
        self.assertIsNone(period["settled"])

        resp = self._settle(self.brand["id"], period_id)
        self.assertEqual(resp.status_code, 200, resp.text)
        settled = resp.json()["period"]["settled"]
        self.assertEqual(
            set(settled.keys()),
            {"spend", "revenue", "settled_at", "late_spend_since", "late_revenue_since"},
        )
        self.assertEqual(settled["late_spend_since"], 0)
        self.assertEqual(settled["late_revenue_since"], 0)


if __name__ == "__main__":
    unittest.main()
