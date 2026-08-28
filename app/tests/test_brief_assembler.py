"""app/tests/test_brief_assembler.py — 創意簡報組裝器（票 03-brief-assembler）。

純組裝、不呼叫 AI，測試一律虛構品牌，隔離 DB。核准計畫與切角格照 ticket 02 的既有測試
先例（test_ads_creative_theme.py）直接用原生 SQL 灌資料，不必真的跑一輪 AI 計畫生成。
"""

import unittest

from app.ads import brief_assembler as ba
from app.ads import repository as ads_repo
from app.ads import theme_repository as theme_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db

ACTOR = "測試員"

_PLAN = {
    "summary": "測試打法：主打省錢誘因",
    "audience": {"cold": {"description": "測試受眾", "available": True},
                "warm": {"available": False}, "hot": {"available": False}, "exclusions": []},
    "angles": [{"title": "省錢誘因", "message": "第一杯只要 39 元", "why": "", "product_id": None}],
}


class _Base(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.brand = bi_repo.create_brand(self.conn, name="虛構晨光咖啡（簡報票）",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        self.product_id = bi_repo.create_product(self.conn, self.bid, name="虛構濾掛組",
                                                  actor=ACTOR)["id"]
        self.cycle_id = ads_repo.create_cycle(
            self.conn, self.bid, product_ids=[self.product_id],
            pain_value=5, objective="sales", actor=ACTOR,
        )["id"]
        self.cell_id = db.new_id("exc")
        self.conn.execute(
            "INSERT INTO experiment_cell (id, org_id, campaign_cycle_id, brand_id, product_id,"
            " creative_angle, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (self.cell_id, db.DEV_ORG_ID, self.cycle_id, self.bid, self.product_id,
             "價格敏感：第一杯 39 元", db.now_iso()),
        )
        self.conn.commit()

    def _insert_plan(self, *, status: str = "approved", plan: dict = None):
        self.conn.execute(
            "INSERT INTO campaign_plan (id, org_id, campaign_cycle_id, brand_id, plan_version,"
            " plan_json, status, approved_by, approved_at, created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (db.new_id("cpl"), db.DEV_ORG_ID, self.cycle_id, self.bid, 1,
             db.jsonb(plan or _PLAN), status,
             ACTOR if status == "approved" else None,
             db.now_iso() if status == "approved" else None, db.now_iso()),
        )
        self.conn.commit()

    def _assemble(self, **overrides):
        kwargs = dict(experiment_cell_id=self.cell_id, format_key="single_image",
                     theme_count=2, actor=ACTOR)
        kwargs.update(overrides)
        return ba.assemble_brief(self.conn, self.bid, self.cycle_id, **kwargs)


class ElevenItemsTest(_Base):
    """簡報物件含全部 11 項；沒有既有主題時該項為空清單。"""

    def setUp(self):
        super().setUp()
        self._insert_plan()

    def test_brief_carries_all_eleven_items_with_correct_shape(self):
        brief, err = self._assemble()
        self.assertIsNone(err)
        self.assertIsInstance(brief, ba.CreativeBrief)

        # 1. 品牌＋檔期（含 offer）
        self.assertEqual(brief.brand["id"], self.bid)
        self.assertEqual(brief.cycle["id"], self.cycle_id)
        self.assertIsNone(brief.offer)  # 這期沒掛 offer
        # 2. 核准計畫
        self.assertEqual(brief.plan["summary"], _PLAN["summary"])
        # 3. 切角
        self.assertEqual(brief.cell["id"], self.cell_id)
        self.assertEqual(brief.cell["creative_angle"], "價格敏感：第一杯 39 元")
        # 4. 品牌智庫 context
        self.assertIsInstance(brief.brand_context, str)
        # 5. 方法論
        self.assertIsInstance(brief.methodology, str)
        # 6. 顧客語料
        self.assertIsInstance(brief.customer_voice, str)
        self.assertFalse(brief.customer_voice_available)  # 沒建過語料
        # 7. 拒絕記憶
        self.assertEqual(brief.rejection_constraints, [])
        # 8. 指紋語彙
        self.assertIsInstance(brief.fingerprint_vocabulary, str)
        self.assertTrue(brief.fingerprint_vocabulary)
        # 9. 格式 key
        self.assertEqual(brief.format_key, "single_image")
        # 10. 生成範圍
        self.assertEqual(brief.generation_scope,
                         {"experiment_cell_id": self.cell_id, "format_key": "single_image",
                          "theme_count": 2})
        # 11. 同格既有主題摘要——沒有主題時為空清單
        self.assertEqual(brief.existing_themes_summary, [])


class OfferInclusionTest(_Base):
    """檔期掛 offer 時，offer 內容一定在簡報裡。"""

    def setUp(self):
        super().setUp()
        self._insert_plan()
        self.offer_id = db.new_id("ofr")
        self.conn.execute(
            "INSERT INTO offer (id, org_id, brand_id, product_scope_json, name, offer_type, terms,"
            " valid_from, valid_to, status, created_at, updated_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (self.offer_id, db.DEV_ORG_ID, self.bid, db.jsonb(["brand"]), "測試優惠：第二件半價",
             "discount", "限量 100 份", "2026-08-01", "2026-08-31", "active",
             db.now_iso(), db.now_iso()),
        )
        self.conn.execute("UPDATE campaign_cycle SET offer_id = %s WHERE id = %s",
                          (self.offer_id, self.cycle_id))
        self.conn.commit()

    def test_offer_content_is_in_brief_when_cycle_has_offer(self):
        brief, err = self._assemble()
        self.assertIsNone(err)
        self.assertIsNotNone(brief.offer)
        self.assertEqual(brief.offer["id"], self.offer_id)
        self.assertEqual(brief.offer["name"], "測試優惠：第二件半價")
        self.assertEqual(brief.offer["terms"], "限量 100 份")

    def test_offer_is_none_when_cycle_has_no_offer(self):
        self.conn.execute("UPDATE campaign_cycle SET offer_id = NULL WHERE id = %s",
                          (self.cycle_id,))
        self.conn.commit()
        brief, err = self._assemble()
        self.assertIsNone(err)
        self.assertIsNone(brief.offer)


class ExistingThemeSummaryTest(_Base):
    """同格已有主題時，摘要（名稱＋指紋）進簡報；別格的主題不算進來。"""

    def setUp(self):
        super().setUp()
        self._insert_plan()

    def test_existing_theme_in_same_cell_is_summarized(self):
        theme_repo.create_theme(
            self.conn, self.bid, campaign_cycle_id=self.cycle_id,
            experiment_cell_id=self.cell_id, format_key="single_image",
            name="虛構主題：晨光第一杯", folder_code="A1B2", actor=ACTOR,
            components=[
                {"component_type": "body", "content": "三分鐘沖一杯好咖啡",
                 "fingerprint_json": {"angle": "benefit", "tone": "warm"}},
                {"component_type": "title", "content": "早晨從一杯開始"},  # 無指紋
            ],
        )
        brief, err = self._assemble()
        self.assertIsNone(err)
        self.assertEqual(len(brief.existing_themes_summary), 1)
        summary = brief.existing_themes_summary[0]
        self.assertEqual(summary["name"], "虛構主題：晨光第一杯")
        self.assertEqual(summary["fingerprints"], [{"angle": "benefit", "tone": "warm"}])

    def test_theme_in_a_different_cell_does_not_leak_in(self):
        other_cell_id = db.new_id("exc")
        self.conn.execute(
            "INSERT INTO experiment_cell (id, org_id, campaign_cycle_id, brand_id, created_at)"
            " VALUES (%s, %s, %s, %s, %s)",
            (other_cell_id, db.DEV_ORG_ID, self.cycle_id, self.bid, db.now_iso()),
        )
        self.conn.commit()
        theme_repo.create_theme(
            self.conn, self.bid, campaign_cycle_id=self.cycle_id,
            experiment_cell_id=other_cell_id, format_key="single_image",
            name="虛構主題：別格的", folder_code="C3D4", actor=ACTOR,
        )
        brief, err = self._assemble()
        self.assertIsNone(err)
        self.assertEqual(brief.existing_themes_summary, [])


class PlanNotApprovedTest(_Base):
    def test_draft_plan_blocks_with_friendly_message(self):
        self._insert_plan(status="draft")
        brief, err = self._assemble()
        self.assertIsNone(brief)
        self.assertEqual(err, ba.PLAN_NOT_APPROVED_MESSAGE)

    def test_no_plan_at_all_blocks_with_friendly_message(self):
        brief, err = self._assemble()
        self.assertIsNone(brief)
        self.assertEqual(err, ba.PLAN_NOT_APPROVED_MESSAGE)


class InputValidationTest(_Base):
    """簡報沒給的資訊等於不存在——組裝前的把關：查無此 id 直接拋例外，不是使用者會在
    畫面上碰到的狀態；trust-boundary 參數（format_key／theme_count）驗證不得省略。"""

    def setUp(self):
        super().setUp()
        self._insert_plan()

    def test_unknown_brand_raises(self):
        with self.assertRaises(ValueError):
            ba.assemble_brief(self.conn, "brd_not_real", self.cycle_id,
                              self.cell_id, "single_image", theme_count=1, actor=ACTOR)

    def test_unknown_cycle_raises(self):
        with self.assertRaises(ValueError):
            ba.assemble_brief(self.conn, self.bid, "ccy_not_real",
                              self.cell_id, "single_image", theme_count=1, actor=ACTOR)

    def test_unknown_cell_raises(self):
        with self.assertRaises(ValueError):
            self._assemble(experiment_cell_id="exc_not_real")

    def test_empty_format_key_raises(self):
        with self.assertRaises(ValueError):
            self._assemble(format_key="")

    def test_non_positive_theme_count_raises(self):
        with self.assertRaises(ValueError):
            self._assemble(theme_count=0)
        with self.assertRaises(ValueError):
            self._assemble(theme_count=-1)

    def test_missing_actor_raises(self):
        with self.assertRaises(ValueError):
            self._assemble(actor="")


class PureAssemblyNoBackDoorTest(_Base):
    """純組裝不呼叫 AI；簡報沒給的資訊等於不存在（不留任何回頭查 DB 的後門參數）。"""

    def setUp(self):
        super().setUp()
        self._insert_plan()

    def test_module_never_touches_the_ai_gateway(self):
        self.assertFalse(hasattr(ba, "gateway"))
        self.assertFalse(hasattr(ba, "PROVIDER"))

    def test_brief_fields_are_plain_data_not_db_handles_or_callbacks(self):
        """簡報是純資料快照：欄位裡不准藏 DB 連線（本專案的連線是 `app.core.db.Conn`
        包裝過的物件，不是裸 driver 連線，所以用「是不是同一個 conn」與
        「有沒有 .execute 這種查 DB 的能力」雙重鴨子定型檢查，而不是 isinstance）
        或任何可呼叫的回頭查 DB 參數。"""
        brief, err = self._assemble()
        self.assertIsNone(err)
        for field_name, value in brief._asdict().items():
            self.assertIsNot(value, self.conn, f"{field_name} 就是那個 DB 連線本身")
            self.assertFalse(hasattr(value, "execute"), f"{field_name} 藏了一個能查 DB 的物件")
            self.assertFalse(callable(value), f"{field_name} 藏了一個可呼叫的回頭查 DB 參數")


if __name__ == "__main__":
    unittest.main()
