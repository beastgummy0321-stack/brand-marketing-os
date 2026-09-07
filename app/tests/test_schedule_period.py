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

import json
import unittest
import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient

import app.main as main
import app.schedule as schedule_module
import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import rule_cards
from app.identity import repository as identity_repo
from app.meta import repository as meta_repo
from app.schedule import period as period_mod
from app.schedule import period_repository as period_repo
from app.schedule import repository as schedule_repo

from .identity_test_helpers import mint_hs256

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

    def _settle(self, brand_id: str, period_id: str, headers: dict | None = None):
        return self.client.post(
            f"/api/schedule/brands/{brand_id}/periods/{period_id}/settle", json={},
            headers=headers,
        )

    def _make_org_with_token(self, suffix: str) -> tuple:
        """A genuinely separate org this client can authenticate AS (not just an org_id
        planted on a crafted row) -- same pattern as test_schedule.py's
        `_ScheduleApiTestBase._make_org()`, needed because `self.client`'s dev token is
        fixed to `coredb.DEV_ORG_ID` otherwise."""
        org_id = self._make_org(suffix)
        user_id = uuid.uuid4()
        email = f"period-test-{suffix}-{user_id.hex[:8]}@example.com"
        identity_repo.create_user(web.conn, user_id, email)
        identity_repo.create_membership(web.conn, org_id, user_id, "owner")
        web.conn.commit()
        return org_id, mint_hs256(sub=str(user_id), email=email)

    @staticmethod
    def _headers(token: str, org_id: str) -> dict:
        return {"Authorization": f"Bearer {token}", "X-Org-Id": org_id}

    def _seed_adset_spend(self, org_id: str, account_id: str, entity_id: str, day: date,
                           spend: float, roas: float | None) -> None:
        """Ticket smart-loop 01: same shape as `_seed_spend()` but a caller-chosen
        `entity_id` and `roas`, so scoring's conservative/optimistic ROAS split has a day
        with a tracked ROAS and a day without."""
        meta_repo.upsert_entity_spend(web.conn, org_id, account_id, [
            {"level": "adset", "entity_id": entity_id, "entity_name": "廣告組合一",
             "campaign_id": entity_id, "adset_id": entity_id, "ad_id": None,
             "spend_date": day, "spend": spend, "impressions": 10, "clicks": 1, "roas": roas,
             "actions": None, "action_values": None,
             "attribution_window": "7d_click,1d_view"},
        ])
        web.conn.commit()

    def _bind_scored_tree(self, org_id: str, brand_id: str, period_id: str, start: date,
                           end: date, *, share: float = 1.0,
                           external_id: str = "adset-scored") -> str:
        """Direct-table equivalent of a succeeded schedule_tree llm_task row plus
        binding.bind_tree() (this file's own '寫表不打真實網路' style; no such tree/bind
        helper existed in this file before this ticket): a bound depth-1 campaign (gets no
        period_node_result row), a bound depth-2 ad set at `external_id` (the node scoring
        actually scores), and the period membership
        bind_tree() would have written. Returns the tree's llm_task id."""
        tree_id = coredb.new_id("llm")
        nodes = [{
            "name": "活動一", "fields": [], "share": None, "warnings": [],
            "children": [{
                "name": "組合一", "fields": [], "share": share, "warnings": [],
                "children": [{"name": "單元一", "fields": [], "share": None, "warnings": [],
                              "children": []}],
            }],
        }]
        payload = {"levels": ["行銷活動", "廣告組合", "廣告"], "budget_level": 2, "nodes": nodes}
        rendered = "說明文字。\n\n```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
        web.conn.execute(
            "INSERT INTO llm_task (id, org_id, brand_id, task_type, context_scope_json,"
            " input_context_ids_json, input_context_hash, knowledge_item_ids_json,"
            " brand_version, prompt_template_id, prompt_template_version, provider, model,"
            " status, attempt_no, started_at, rendered_output)"
            " VALUES (%s, %s, %s, 'schedule_tree', %s, '[]', '', '[]', 1, 'p', 'v1', 'seed',"
            " 'seed', 'succeeded', 1, %s, %s)",
            (tree_id, org_id, brand_id,
             coredb.jsonb({"daily_budget": 1000.0, "plan_index": 0}),
             coredb.now_iso(), rendered),
        )
        channel_id = schedule_repo.ensure_meta_channel(web.conn, org_id)
        schedule_repo.upsert_binding(
            web.conn, org_id=org_id, brand_id=brand_id, channel_id=channel_id, node_key="1",
            node_name_at_bind="活動一", external_id="camp-scored", external_status="ACTIVE",
            source_tree_task_id=tree_id,
        )
        schedule_repo.upsert_binding(
            web.conn, org_id=org_id, brand_id=brand_id, channel_id=channel_id,
            node_key="1.1", node_name_at_bind="組合一", external_id=external_id,
            external_status="ACTIVE", source_tree_task_id=tree_id,
        )
        schedule_repo.insert_period_node_membership(
            web.conn, org_id=org_id, brand_id=brand_id, campaign_period_id=period_id,
            channel_id=channel_id, node_key="1.1", from_date=start, to_date=end,
            source_tree_task_id=tree_id,
        )
        web.conn.commit()
        return tree_id

    def _rebind_node_under_new_tree(self, org_id: str, brand_id: str, node_key: str,
                                     node_name: str, external_id: str) -> None:
        """Only a channel_entity_map row for a SECOND tree at the same node_key -- no
        period_node_membership write, simulating a bind that happened while a different
        period was 'latest' (period_repo.get_latest_period()). Fixture for the ticket's
        contradiction-check trap: bindings_by_node_key()'s overlay would show this row;
        bindings_for_tree(first_tree_id) must not."""
        channel_id = schedule_repo.ensure_meta_channel(web.conn, org_id)
        schedule_repo.upsert_binding(
            web.conn, org_id=org_id, brand_id=brand_id, channel_id=channel_id,
            node_key=node_key, node_name_at_bind=node_name, external_id=external_id,
            external_status="ACTIVE", source_tree_task_id=coredb.new_id("llm"),
        )
        web.conn.commit()

    def _prepare_scored_period(self, org_id: str, brand_id: str, start: date,
                                end: date) -> tuple:
        """Break-even 1.0 (a 100% margin -- the file's fixture path via the `gross_margin`
        rule card, same shortcut the ticket's own plan review flagged for production data),
        a bound Meta account, and one running period covering [start, end]."""
        rule_cards.set_value(web.conn, brand_id, "gross_margin", "gross_margin_rate", 1.0,
                              actor=ACTOR, org_id=org_id)
        account_id = self._bind_account(org_id, brand_id)
        period_id = self._insert_period(org_id=org_id, brand_id=brand_id, start=start, end=end)
        return account_id, period_id

    def _insert_settled_period(self, *, org_id: str, brand_id: str, start: date, end: date,
                                daily_budget: float) -> str:
        """Ticket smart-loop 05 fixture: a `status='settled'` row `next_period_suggestion()`
        reads directly (`period_repo.latest_settled_period()`), same direct-table style as
        `_insert_period()` above rather than running the whole settle() pipeline."""
        period_id = coredb.new_id("cpd")
        web.conn.execute(
            "INSERT INTO campaign_period (id, org_id, brand_id, name, start_date, end_date,"
            " status, daily_budget, currency, settled_spend, settled_revenue, settled_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, 'settled', %s, 'TWD', 0, 0, now())",
            (period_id, org_id, brand_id, f"{start.isoformat()} ~ {end.isoformat()}",
             start, end, daily_budget),
        )
        web.conn.commit()
        return period_id

    def _write_depth2_result(self, *, org_id: str, brand_id: str, period_id: str,
                              channel_id: str, spend: float, revenue_tracked: float | None,
                              roas_optimistic: float | None, breakeven: float | None) -> None:
        """One depth-2 `period_node_result` row, replacing whatever this period had --
        `period_repo.replace_period_node_results()` is DELETE+INSERT, so calling this again
        is literally the ticket's "rows replaced by one X row". Fields the suggestion's own
        arithmetic never reads (`approved_share`, `roas_coverage`, `breakeven_source`,
        `verdict`) get fixed placeholder values -- only NOT NULL, not meaningful here."""
        period_repo.replace_period_node_results(web.conn, org_id, brand_id, period_id, [{
            "source_tree_task_id": coredb.new_id("llm"), "channel_id": channel_id,
            "node_key": "1.1", "depth": 2, "node_name": "組合一", "external_id": "adset-1",
            "approved_share": 1.0, "approved_daily_amount": 100.0, "actual_spend": spend,
            "revenue_tracked": revenue_tracked, "roas_conservative": None,
            "roas_optimistic": roas_optimistic, "roas_coverage": 1.0,
            "breakeven_roas": breakeven, "breakeven_source": "rule_card", "verdict": "win",
            "coordinates_json": None, "settled_at": coredb.now_iso(),
        }])


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


class SettleScoresNodesTest(_PeriodTestBase):
    """data correctness / money (ticket smart-loop 01, ADR 0066): settling a period scores
    every bound depth-2/3 node against the break-even line; a depth-1 binding gets no row.

    Red proof: comment out the `scoring_mod.score_period(...)` call in
    `app/schedule/routes.py`'s `_run_settle()` -> `period_node_result` stays at zero rows ->
    every assertion below that reads that table fails. Verified red before scoring.py was
    wired into `_run_settle()`."""

    def test_settle_scores_bound_node_and_skips_depth_one(self):
        org_id = coredb.DEV_ORG_ID
        brand_id = self.brand["id"]
        start, end = date(2026, 8, 1), date(2026, 8, 5)
        account_id, period_id = self._prepare_scored_period(org_id, brand_id, start, end)
        self._bind_scored_tree(org_id, brand_id, period_id, start, end)
        day_a, day_b = start, start + timedelta(days=1)

        def _settled_row():
            return web.conn.execute(
                "SELECT * FROM period_node_result WHERE campaign_period_id = %s"
                " AND node_key = '1.1'", (period_id,),
            ).fetchone()

        # day A spend 100 roas 3.0, day B spend 100 roas None -> conservative 1.5, optimistic
        # 3.0, coverage 0.5 -> win against break-even 1.0.
        self._seed_adset_spend(org_id, account_id, "adset-scored", day_a, 100.0, 3.0)
        self._seed_adset_spend(org_id, account_id, "adset-scored", day_b, 100.0, None)
        resp = self._settle(brand_id, period_id)
        self.assertEqual(resp.status_code, 200, resp.text)

        rows = list(web.conn.execute(
            "SELECT node_key, depth FROM period_node_result WHERE campaign_period_id = %s",
            (period_id,),
        ))
        self.assertEqual(rows, [{"node_key": "1.1", "depth": 2}])  # the depth-1 bind gets none
        row = _settled_row()
        self.assertAlmostEqual(float(row["actual_spend"]), 200.0, places=2)
        self.assertAlmostEqual(float(row["roas_conservative"]), 1.5, places=4)
        self.assertAlmostEqual(float(row["roas_optimistic"]), 3.0, places=4)
        self.assertAlmostEqual(float(row["roas_coverage"]), 0.5, places=4)
        self.assertEqual(row["verdict"], "win")

        # day A roas 0.5 -> conservative 0.25, optimistic 0.5 < 1.0 -> lose.
        self._seed_adset_spend(org_id, account_id, "adset-scored", day_a, 100.0, 0.5)
        self.assertEqual(self._settle(brand_id, period_id).status_code, 200)
        self.assertEqual(_settled_row()["verdict"], "lose")

        # day A roas 1.2 -> conservative 0.6, optimistic 1.2 -> unclear. Catches a verdict
        # computed from optimistic ROAS alone (cheapest-wrong-implementation trap (b)),
        # which would call this a win.
        self._seed_adset_spend(org_id, account_id, "adset-scored", day_a, 100.0, 1.2)
        self.assertEqual(self._settle(brand_id, period_id).status_code, 200)
        self.assertEqual(_settled_row()["verdict"], "unclear")

        # remove both days -> actual_spend 0, verdict unclear, row still written.
        web.conn.execute(
            "DELETE FROM meta_entity_spend WHERE ad_account_id = %s AND entity_id = %s",
            (account_id, "adset-scored"),
        )
        web.conn.commit()
        self.assertEqual(self._settle(brand_id, period_id).status_code, 200)
        row = _settled_row()
        self.assertEqual(float(row["actual_spend"]), 0.0)
        self.assertEqual(row["verdict"], "unclear")

    def test_resettle_rewrites_one_row_and_keeps_naming_the_periods_own_tree(self):
        org_id = coredb.DEV_ORG_ID
        brand_id = self.brand["id"]
        start, end = date(2026, 7, 1), date(2026, 7, 5)
        account_id, period_id = self._prepare_scored_period(org_id, brand_id, start, end)
        first_tree_id = self._bind_scored_tree(org_id, brand_id, period_id, start, end)
        self._seed_adset_spend(org_id, account_id, "adset-scored", start, 100.0, 2.0)

        resp = self._settle(brand_id, period_id)
        self.assertEqual(resp.status_code, 200, resp.text)
        first_settled_at = web.conn.execute(
            "SELECT settled_at FROM period_node_result WHERE campaign_period_id = %s"
            " AND node_key = '1.1'", (period_id,),
        ).fetchone()["settled_at"]

        # Cheapest-wrong-implementation trap (a): a second tree also binds "1.1", to a
        # DIFFERENT external id, with a later created_at -- bindings_by_node_key()'s overlay
        # would show this row; scoring must keep reading bindings_for_tree(first_tree_id),
        # since this period's own membership was never rebound to the second tree.
        self._rebind_node_under_new_tree(org_id, brand_id, "1.1", "組合一",
                                          "adset-scored-from-a-later-tree")

        resp = self._settle(brand_id, period_id)
        self.assertEqual(resp.status_code, 200, resp.text)
        rows = list(web.conn.execute(
            "SELECT external_id, source_tree_task_id, settled_at FROM period_node_result"
            " WHERE campaign_period_id = %s", (period_id,),
        ))
        self.assertEqual(len(rows), 1)  # still exactly one row per node
        self.assertEqual(rows[0]["external_id"], "adset-scored")
        self.assertEqual(rows[0]["source_tree_task_id"], first_tree_id)
        self.assertNotEqual(rows[0]["settled_at"], first_settled_at)  # settled_at updated


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
        # Ticket smart-loop 01 done-check 3: a 404'd settle scores nothing either.
        self.assertEqual(list(web.conn.execute(
            "SELECT * FROM period_node_result WHERE campaign_period_id = %s", (period_id,),
        )), [])

    def test_settling_org_bs_period_leaves_org_as_shared_external_id_node_unscored(self):
        """Ticket smart-loop 01 done-check 3, contradiction check #1: Meta ids are global,
        so two orgs' nodes can legitimately bind to the same literal external_id. Settling
        org B's own period must not write a row for org A's node, and reading org A's own
        period must return none of org B's spend -- seeding two DIFFERENT external ids would
        leave this test unable to tell a real fix from a coincidence."""
        org_a = coredb.DEV_ORG_ID
        brand_a = self.brand["id"]
        start, end = date(2026, 6, 1), date(2026, 6, 5)
        shared_external_id = "shared-ext-id"
        _account_a, period_a = self._prepare_scored_period(org_a, brand_a, start, end)
        self._bind_scored_tree(org_a, brand_a, period_a, start, end,
                                external_id=shared_external_id)

        org_b, token_b = self._make_org_with_token("shared-ext-id-b")
        brand_b = bi_repo.create_brand(
            web.conn, org_id=org_b, name="測試品牌：跨組織同 external_id", client_name=None,
            actor=ACTOR,
        )["id"]
        web.conn.commit()
        account_b, period_b = self._prepare_scored_period(org_b, brand_b, start, end)
        self._bind_scored_tree(org_b, brand_b, period_b, start, end,
                                external_id=shared_external_id)
        self._seed_adset_spend(org_b, account_b, shared_external_id, start, 999.0, 5.0)

        # Org B settles its OWN period, genuinely authenticated as org B (self.client's
        # fixed dev token is org A/DEV_ORG_ID) -- this succeeds, unlike the 404 test above.
        resp_b = self._settle(brand_b, period_b, headers=self._headers(token_b, org_b))
        self.assertEqual(resp_b.status_code, 200, resp_b.text)
        b_row = web.conn.execute(
            "SELECT actual_spend FROM period_node_result WHERE campaign_period_id = %s"
            " AND node_key = '1.1'", (period_b,),
        ).fetchone()
        self.assertAlmostEqual(float(b_row["actual_spend"]), 999.0, places=2)

        # Org A settles its own (still spend-less) period next -- org B's settle wrote
        # nothing under org A's period_id, and org A's own read shows the real zero, not
        # org B's 999.
        self.assertEqual(list(web.conn.execute(
            "SELECT * FROM period_node_result WHERE campaign_period_id = %s", (period_a,),
        )), [])
        resp_a = self._settle(brand_a, period_a)
        self.assertEqual(resp_a.status_code, 200, resp_a.text)
        a_row = web.conn.execute(
            "SELECT actual_spend FROM period_node_result WHERE campaign_period_id = %s"
            " AND node_key = '1.1'", (period_a,),
        ).fetchone()
        self.assertEqual(float(a_row["actual_spend"]), 0.0)


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
             "settle_advice_date", "settled", "node_results"},
        )
        self.assertIsNone(period["settled"])
        self.assertEqual(period["node_results"], [])

        resp = self._settle(self.brand["id"], period_id)
        self.assertEqual(resp.status_code, 200, resp.text)
        settled_period = resp.json()["period"]
        settled = settled_period["settled"]
        self.assertEqual(
            set(settled.keys()),
            {"spend", "revenue", "settled_at", "late_spend_since", "late_revenue_since"},
        )
        self.assertEqual(settled["late_spend_since"], 0)
        self.assertEqual(settled["late_revenue_since"], 0)
        # No tree/binding was ever set up for this period, so scoring writes zero rows.
        self.assertEqual(settled_period["node_results"], [])


class NextPeriodSuggestionTest(_PeriodTestBase):
    """Ticket smart-loop 05: `period.next_period_suggestion()` -- data correctness (spend-
    weighted direction, budget arithmetic, rolled dates) and API contract (`None` before any
    settled period).

    Red proof: `next_period_suggestion()` returning `None` unconditionally passes
    `test_none_when_no_settled_period` but fails every assertion in
    `test_direction_budget_dates_and_step_rate` starting at case (a) -- verified red before
    the real arithmetic was written."""

    def test_direction_budget_dates_and_step_rate(self):
        org_id = coredb.DEV_ORG_ID
        brand_id = self.brand["id"]
        channel_id = schedule_repo.ensure_meta_channel(web.conn, org_id)
        start, end = date(2026, 9, 1), date(2026, 9, 7)
        period_id = self._insert_settled_period(
            org_id=org_id, brand_id=brand_id, start=start, end=end, daily_budget=2000.0)

        # (a) one win row: spend 100, revenue 300, optimistic 3.0, breakeven 1.0 -> up, 2400,
        # dates roll to the day after `end` for the same number of days.
        self._write_depth2_result(org_id=org_id, brand_id=brand_id, period_id=period_id,
                                   channel_id=channel_id, spend=100.0, revenue_tracked=300.0,
                                   roas_optimistic=3.0, breakeven=1.0)
        suggestion = period_mod.next_period_suggestion(web.conn, org_id, brand_id)
        self.assertIsNotNone(suggestion)
        self.assertEqual(suggestion["based_on_period_id"], period_id)
        self.assertEqual(suggestion["direction"], "up")
        self.assertEqual(suggestion["daily_budget"], 2400.0)
        self.assertEqual(suggestion["start_date"], "2026-09-08")
        self.assertEqual(suggestion["end_date"], "2026-09-14")

        # (b) rows replaced by one lose row: spend 100, revenue 50, optimistic 0.5 -> down, 1600.
        self._write_depth2_result(org_id=org_id, brand_id=brand_id, period_id=period_id,
                                   channel_id=channel_id, spend=100.0, revenue_tracked=50.0,
                                   roas_optimistic=0.5, breakeven=1.0)
        suggestion = period_mod.next_period_suggestion(web.conn, org_id, brand_id)
        self.assertEqual(suggestion["direction"], "down")
        self.assertEqual(suggestion["daily_budget"], 1600.0)

        # (c) rows replaced by an untracked (actual_spend 0) row -> hold, unchanged, and the
        # "why" sentence names 看不出 (no verdict was computable, not merely "not adopted").
        self._write_depth2_result(org_id=org_id, brand_id=brand_id, period_id=period_id,
                                   channel_id=channel_id, spend=0.0, revenue_tracked=None,
                                   roas_optimistic=None, breakeven=1.0)
        suggestion = period_mod.next_period_suggestion(web.conn, org_id, brand_id)
        self.assertEqual(suggestion["direction"], "hold")
        self.assertEqual(suggestion["daily_budget"], 2000.0)
        self.assertIn("看不出", suggestion["why"])

        # (e) restore (a)'s win row, then set step_rate to 10 -> the same win now gives 2200
        # (catches rounding the percentage as a fraction: 20 -> x21 would give 2420, not read
        # 2200 either way, so this specifically pins the /100 conversion).
        self._write_depth2_result(org_id=org_id, brand_id=brand_id, period_id=period_id,
                                   channel_id=channel_id, spend=100.0, revenue_tracked=300.0,
                                   roas_optimistic=3.0, breakeven=1.0)
        rule_cards.set_value(web.conn, brand_id, "schedule_budget", "step_rate", 10.0,
                              actor=ACTOR, org_id=org_id)
        suggestion = period_mod.next_period_suggestion(web.conn, org_id, brand_id)
        self.assertEqual(suggestion["direction"], "up")
        self.assertEqual(suggestion["daily_budget"], 2200.0)

    def test_none_when_no_settled_period(self):
        org_id = coredb.DEV_ORG_ID
        brand_id = self.brand["id"]
        self.assertIsNone(period_mod.next_period_suggestion(web.conn, org_id, brand_id))


class NextPeriodSuggestionOverlapTest(_PeriodTestBase):
    """Ticket smart-loop 05 check 2: a non-settled period covering part of the suggested
    window is reported, not hidden -- the suggestion is still made (dates are the rule per
    the ticket's contradiction check), the collision is only ever a warning."""

    def test_overlap_with_a_planning_period_is_named_absence_is_empty(self):
        org_id = coredb.DEV_ORG_ID
        brand_id = self.brand["id"]
        channel_id = schedule_repo.ensure_meta_channel(web.conn, org_id)
        start, end = date(2026, 9, 1), date(2026, 9, 7)
        period_id = self._insert_settled_period(
            org_id=org_id, brand_id=brand_id, start=start, end=end, daily_budget=2000.0)
        self._write_depth2_result(org_id=org_id, brand_id=brand_id, period_id=period_id,
                                   channel_id=channel_id, spend=100.0, revenue_tracked=300.0,
                                   roas_optimistic=3.0, breakeven=1.0)

        suggestion = period_mod.next_period_suggestion(web.conn, org_id, brand_id)
        self.assertEqual(suggestion["overlaps"], [])  # nothing else exists yet

        # 09-10 ~ 09-12 sits inside the suggested 09-08 ~ 09-14 window.
        self._insert_period(org_id=org_id, brand_id=brand_id, start=date(2026, 9, 10),
                             end=date(2026, 9, 12), status="planning")
        suggestion = period_mod.next_period_suggestion(web.conn, org_id, brand_id)
        self.assertIn("2026-09-10 ~ 2026-09-12", suggestion["overlaps"])


if __name__ == "__main__":
    unittest.main()
