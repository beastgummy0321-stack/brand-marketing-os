"""app/tests/test_dashboard_guide_card_links.py — 指南卡按鈕不得指向不存在的頁面。

為什麼要有這支：test_dashboard_guide_cards.py 斷言的是「程式產出的網址字串 ==
測試裡寫死的同一個字串」，兩邊都是死字面——**改掉舊路由的網址時，那些測試照樣全綠，
但畫面上的按鈕會靜默 404**（code review 2026-08-06 發現的缺口，階段 4 全站遷移會
大量改動舊路由，屆時這個缺口就是真的斷鏈）。

這支的做法：用真的品牌＋真的檔期把每條規則各觸發一次，拿它產出的 action_url
**實際打一次**，只要回 404 就讓測試紅。這樣「路由改名」跟「規則寫錯網址」都擋得住。

CASES 必須涵蓋 guide_cards.RULES 的每一條（test_every_rule_has_a_link_case 把關）
——以後新增規則卻忘了顧網址，這裡會當場叫。

TestClient 模式。測試品牌一律虛構。
"""

import os
import unittest

os.environ["BRAND_OS_TODAY"] = "2026-08-05"  # 凍結時鐘：與其他儀表板測試檔一致

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import db as coredb  # noqa: E402
from app.core.db import new_id, now_utc  # noqa: E402
from app.dashboard import guide_cards  # noqa: E402
from app.intake import state as intake_state  # noqa: E402

ACTOR = "測試員"


def _insert_cycle(conn, brand_id: str) -> str:
    """比照 test_dashboard_guide_cards_wiring.py 直接塞一列（測試檔豁免跨層 SQL 掃描）。

    比那邊多塞一個 derived_plan_json：期長／日預算是從這欄解出來的
    （app/ads/routes_common.py `_cycle_view`），檔期頁面拿它排版。真實檔期一律經由
    `create_cycle` 建立、這欄必定有值，所以測試資料也要有——否則測到的是「頁面能不能
    扛住不可能出現的殘缺資料」，不是這支要測的連結完整性。
    """
    cycle_id = new_id("ccy")
    ts = now_utc()
    conn.execute(
        "INSERT INTO campaign_cycle (id, org_id, brand_id, product_scope_json, objective,"
        " budget, currency, start_date, end_date, channels_json, status, archived,"
        " plan_version, phase, derived_plan_json, created_at, updated_at) VALUES"
        " (%s, %s, %s, '[]', 'sales', 5000, 'TWD', '2026-07-20', '2026-08-20',"
        " '[\"meta\"]', 'LIVE', false, 0, 'normal', %s, %s, %s)",
        (cycle_id, coredb.DEV_ORG_ID, brand_id, coredb.jsonb(
            {"duration_days": 14, "daily_budget": 357.14, "daily_stop_loss": 714.28,
             "pause_threshold_spend": 2500, "daily_below_floor": False}), ts, ts),
    )
    conn.commit()
    return cycle_id


class GuideCardLinksResolveTest(unittest.TestCase):
    """每條規則產出的 action_url 都要指到真的存在的頁面。"""

    @classmethod
    def setUpClass(cls):
        # setUpClass 跑在 conftest.py 逐測試的 _bound_connection fixture 之外，
        # 這裡自己借一條連線把班級層級的固定資料建好（跟 conftest.py 同一個池子、
        # 同一個 schema，之後每個測試方法透過 TestClient 或自己的 fixture 借到的
        # 另一條連線都看得到這裡 commit 過的資料）。
        with coredb.connection():
            brand = bi_repo.create_brand(
                main.conn, name="虛構連結檢查花坊", client_name=None, actor=ACTOR,
                    org_id=coredb.DEV_ORG_ID)
            cls.brand_id = brand["id"]
            cls.cycle_id = _insert_cycle(main.conn, cls.brand_id)
            # 票 B3-intake：intake_in_progress 的網址要真的能接到一份進行中草稿，不能只是
            # 拼字串——真的開一份草稿，用它算出來的 resume_path 當這條規則的測試網址。
            draft = intake_state.new_draft(
                cls.brand_id, brand["name"], description="測試用品牌描述文字。",
                urls=[], photos=[], actor=ACTOR, conn=main.conn)
            cls.intake_resume_path = draft["resume_path"]
        cls.client = TestClient(main.app)

    def _facts(self, **overrides) -> dict:
        base = {
            "brand_id": self.brand_id,
            "conversion_goal": "purchase",
            "pending_facts_count": 0,
            "active_cycle": None,
            "reading_ready": False,
            "next_cycle_draft_ready": False,
            "campaign_reminder": None,
            "pacing_alert": None,
        }
        base.update(overrides)
        return base

    def _cases(self) -> dict:
        """規則 id → 能觸發該規則的 facts。每條規則各一組（有些規則互斥，不能共用一份）。"""
        cycle = {"id": self.cycle_id, "stage_label": "素材"}
        return {
            "conversion_goal_missing": self._facts(conversion_goal=None),
            # action_url 為 None 時走 fallback，這裡刻意不給，測的是 fallback 那條網址
            "pacing_alert": self._facts(
                pacing_alert={"kind": "overspend", "action_url": None}),
            "reading_unread": self._facts(
                active_cycle={"id": self.cycle_id, "stage_label": None}, reading_ready=True),
            "next_cycle_draft": self._facts(
                active_cycle={"id": self.cycle_id, "stage_label": None},
                next_cycle_draft_ready=True),
            "cycle_stage": self._facts(active_cycle=cycle),
            "pending_facts": self._facts(pending_facts_count=3),
            "campaign_calendar": self._facts(campaign_reminder={
                "id": "cny_2026", "name": "農曆新年", "days_until": 28,
                "kind": "prep", "weeks_until": 4, "tier_label": "大檔"}),
            "intake_in_progress": self._facts(
                intake_draft={"step": 2, "resume_path": self.intake_resume_path}),
        }

    def test_every_rule_has_a_link_case(self):
        """CASES 要涵蓋每一條登記規則——新增規則卻沒在這裡補一組 facts，當場叫。"""
        self.assertEqual(
            set(self._cases()), set(guide_cards.RULES),
            "guide_cards.RULES 有規則沒被連結檢查涵蓋（新增規則時要在 _cases() 補一組"
            " 能觸發它的 facts，否則它的按鈕網址沒人守）",
        )

    def test_every_guide_card_link_resolves(self):
        """核心：拿每條規則真正產出的網址去打，回 404 就是斷鏈。"""
        broken = []
        for rule_id, facts in self._cases().items():
            card = guide_cards.RULES[rule_id](facts)
            self.assertIsNotNone(card, f"{rule_id} 的 facts 沒能觸發該規則，這組 facts 要修")
            url = card["action_url"]
            status = self.client.get(url, follow_redirects=False).status_code
            if status == 404:
                broken.append(f"{rule_id} → {url}（404）")
        self.assertEqual(
            broken, [],
            "以下指南卡按鈕指向不存在的頁面（八成是舊路由改名了沒同步"
            " app/dashboard/guide_cards.py）：\n" + "\n".join(broken),
        )
