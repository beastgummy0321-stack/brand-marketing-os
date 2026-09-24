"""app/tests/test_ads_judgment.py — F04-I08 falsifiers: `app/ads/judgment.py` is pure string
rules (照 `app/tests/test_ads_budget.py` 的純函式測試寫法，judgment 那半不需要 DB)。F28-I06 起
`GET .../home` 是月份總覽（`test_ads_home_overview.py`），舊首頁路由測試隨路由一起刪除。
"""

import unittest
from datetime import date

import app.shared.web as web
from app.ads import judgment
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo

ACTOR = "測試員"


class CampaignJudgmentLiveTest(unittest.TestCase):
    def test_budget_spent_faster_than_time_is_warn(self):
        campaign = {
            "status": "live", "start_date": date(2026, 9, 1), "end_date": date(2026, 9, 30),
            "budget_total": 10000, "spend": 6000,
        }
        result = judgment.campaign_judgment(campaign, today=date(2026, 9, 12))
        self.assertEqual(result["tone"], "warn")
        self.assertIn("花得比時間快", result["text"])
        self.assertIn("第 12／30 天", result["detail"])

    def test_no_budget_total_is_neutral_and_never_mentions_zero(self):
        campaign = {
            "status": "live", "start_date": date(2026, 9, 1), "end_date": date(2026, 9, 30),
            "budget_total": None, "spend": 0,
        }
        result = judgment.campaign_judgment(campaign, today=date(2026, 9, 12))
        self.assertEqual(result["tone"], "neutral")
        self.assertEqual(result["detail"], "還沒有可比的總預算")
        self.assertNotIn("0", result["text"])
        self.assertNotIn("0", result["detail"])

    def test_no_outcome_rows_is_neutral_and_never_mentions_zero_spend(self):
        campaign = {
            "status": "live", "start_date": date(2026, 9, 1), "end_date": date(2026, 9, 30),
            "budget_total": 10000, "spend": None,
        }
        result = judgment.campaign_judgment(campaign, today=date(2026, 9, 12))
        self.assertEqual(result["tone"], "neutral")
        self.assertEqual(result["text"], "投放中")
        self.assertNotIn("已花費", result["detail"])
        self.assertNotIn("NT$", result["detail"])


class CampaignJudgmentDraftTest(unittest.TestCase):
    def test_draft_without_strategy(self):
        campaign = {"status": "draft", "budget_basis_json": {}}
        result = judgment.campaign_judgment(campaign, today=date(2026, 9, 12))
        self.assertEqual(result["text"], "還沒產生策略")

    def test_draft_with_strategy_not_adopted(self):
        campaign = {"status": "draft", "budget_basis_json": {"strategy": {"allocation": []}}}
        result = judgment.campaign_judgment(campaign, today=date(2026, 9, 12))
        self.assertEqual(result["text"], "策略已產生，還沒採用")


class BrandHeadlineTest(unittest.TestCase):
    def test_all_zero_says_no_decision_needed(self):
        counts = {"running": 0, "upcoming": 0, "ended": 0, "needs_decision": 0}
        result = judgment.brand_headline(counts)
        self.assertIn("目前沒有需要你決定的事", result["facts"])


class ActionLineTest(unittest.TestCase):
    def test_budget_change_formats_before_after_as_money(self):
        action = {
            "kind": "budget", "before_json": {"daily_budget": 1000},
            "after_json": {"daily_budget": 1500}, "approved_by": "測試員",
            "sync_state": "pending_manual", "created_at": date(2026, 9, 12),
        }
        result = judgment.action_line(
            action, campaign_name="活動一", target_name="投放組 A", today=date(2026, 9, 12),
        )
        self.assertIn("已記錄", result["title"])
        self.assertIn("預算調整", result["title"])
        self.assertIn("NT$ 1,000 → NT$ 1,500", result["detail"])

    def test_detail_never_prints_approved_by_id(self):
        action = {
            "kind": "publish", "approved_by": "b0a57eef-0000-4000-8000-000000000123",
            "sync_state": "pending_manual", "created_at": date(2026, 9, 12),
        }
        result = judgment.action_line(
            action, campaign_name="活動一", target_name=None, today=date(2026, 9, 12),
        )
        self.assertEqual(result["detail"], "尚無足夠的本次平台讀回證據。")
        self.assertNotIn("b0a57eef", result["detail"])

    def test_approval_and_user_reports_do_not_claim_platform_completion(self):
        for kind in ("publish", "budget", "date", "pause", "creative"):
            for state, expected in (("pending", "已本機核准"), ("reported", "使用者已回報")):
                with self.subTest(kind=kind, state=state):
                    result = judgment.action_line(
                        {"kind": kind, "change_set_id": "local", "verification_state": state,
                         "created_at": date(2026, 9, 12)},
                        campaign_name="活動一", target_name=None, today=date(2026, 9, 12),
                    )
                    self.assertIn(expected, result["title"])
                    self.assertNotIn("發布了", result["title"])
                    self.assertNotIn("暫停了", result["title"])
                    self.assertIn("讀回核對", result["detail"])

    def test_legacy_sync_markers_and_confirmation_without_evidence_are_not_upgraded(self):
        for sync in ("auto_synced", "confirmed_manual", "pending_manual"):
            result = judgment.action_line(
                {"kind": "publish", "sync_state": sync, "verification_state": "confirmed",
                 "created_at": date(2026, 9, 12)}, campaign_name="活動一", target_name=None,
                today=date(2026, 9, 12),
            )
            self.assertNotIn("已讀回核對", result["title"])
            self.assertNotIn("已手動同步", result["detail"])
            self.assertNotIn("自動同步", result["detail"])

    def test_readback_confirms_settings_without_claiming_delivery(self):
        result = judgment.action_line(
            {"kind": "publish", "verification_state": "confirmed",
             "evidence_json": {"setting_matches": True, "delivery_confirmed": False},
             "verified_at": date(2026, 9, 12), "created_at": date(2026, 9, 12)},
            campaign_name="活動一", target_name=None, today=date(2026, 9, 12),
        )
        self.assertIn("已讀回核對", result["title"])
        self.assertIn("不代表已投遞", result["detail"])


class CampaignDetailJudgmentTest(unittest.TestCase):
    def test_campaign_detail_has_judgment_and_action_lines_and_keeps_actions(self):
        from app.core import db as coredb

        org_id = coredb.DEV_ORG_ID
        brand_id = bi_repo.create_brand(
            web.conn, org_id=org_id, name="測試品牌：投放中心判斷句", client_name=None,
            actor=ACTOR,
        )["id"]
        campaign = {
            "name": "判斷句測試 Campaign", "goal_text": "驗證判斷句", "objective": "購買",
            "target_cost": 300,
        }
        campaign_id = ads_repo.create_campaign(
            web.conn, org_id, brand_id, campaign, created_by=ACTOR,
        )["id"]
        web.conn.commit()

        detail = ads_repo.campaign_detail(web.conn, org_id, brand_id, campaign_id)
        self.assertIsNotNone(detail)
        self.assertIn("judgment", detail)
        self.assertIn("action_lines", detail)
        self.assertIn("actions", detail)


class ConversionLabelsTest(unittest.TestCase):
    """F05-I12：「每筆名單成本」與 CPA 是同一個算式的兩個名字——只換 label，不新增
    指標（§8 第 4 條）。"""

    def test_purchase_goal(self):
        labels = judgment.conversion_labels("purchase")
        self.assertEqual(labels, {"conversion": "購買", "count": "購買數", "cpa": "每次購買成本"})

    def test_lead_goal(self):
        labels = judgment.conversion_labels("lead")
        self.assertEqual(labels, {"conversion": "名單", "count": "名單數", "cpa": "每筆名單成本"})

    def test_booking_goal(self):
        labels = judgment.conversion_labels("booking")
        self.assertEqual(labels, {"conversion": "預約", "count": "預約數", "cpa": "每次預約成本"})

    def test_awareness_goal(self):
        labels = judgment.conversion_labels("awareness")
        self.assertEqual(labels, {"conversion": "成效", "count": "成效次數", "cpa": "每次成效成本"})

    def test_none_falls_back_to_purchase(self):
        self.assertEqual(judgment.conversion_labels(None), judgment.conversion_labels("purchase"))

    def test_unknown_string_falls_back_to_purchase(self):
        self.assertEqual(
            judgment.conversion_labels("something_new"), judgment.conversion_labels("purchase"),
        )


if __name__ == "__main__":
    unittest.main()
