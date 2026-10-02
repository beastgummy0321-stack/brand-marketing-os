"""app/tests/test_workbench_proof_vocabulary.py — F38-I04: the copy prompt offers only the proof
kinds the brand has registered evidence for (F38 decision 1), and `brief_text` writes 限時限量 only
against the handed-over deadline (decision 3). Fixture style of `test_workbench_copy_length.py`;
coordinates are seeded through the schedule API, as `test_workbench_image_round.py` does.
"""

import json
import unittest

from fastapi.testclient import TestClient

import app.background as background_module
import app.main as main
import app.shared.web as web
import app.workbench as workbench_module
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.llm import providers
from app.workbench import jobs as workbench_jobs
from app.workbench import prompts
from app.workbench import repository as workbench_repo

ACTOR = "測試員"
_PROOF_LABELS = [
    "顧客評論原話", "專家背書", "檢驗報告／認證", "銷售數據", "媒體報導", "創辦人第一手",
]


def _cjk(n: int) -> str:
    base = "測試文案內容真實好用推薦體驗品質細節故事風格"
    return (base * (n // len(base) + 1))[:n]


def _proof_section(prompt: str) -> str:
    start = prompt.index("### proof\n")
    end = prompt.find("\n\n", start)
    return prompt[start:end if end != -1 else None]


def _offer_block(prompt: str) -> str:
    start = prompt.index("## 優惠、背書與已登記的證據來源")
    end = prompt.find("\n\n", start)
    return prompt[start:end if end != -1 else None]


class _CopyRunBase(unittest.TestCase):
    def setUp(self):
        workbench_module.register_tasks()
        self.org_id = coredb.DEV_ORG_ID
        self.brand_id = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：證據選單", client_name=None,
            actor=ACTOR,
        )["id"]
        self.product = bi_repo.create_product(
            web.conn, self.brand_id, name="測試產品：證據選單", actor=ACTOR,
        )
        web.conn.commit()
        resp = TestClient(main.app).get(f"/api/schedule/brands/{self.brand_id}/coordinates")
        assert resp.status_code == 200, resp.text
        self._orig_provider = workbench_jobs.PROVIDER

    def tearDown(self):
        workbench_jobs.PROVIDER = self._orig_provider

    def _run_copy(self, proof_label: str, *, product_id: str | None = None,
                  coordinates: dict | None = None) -> tuple[str, dict]:
        brief_id = workbench_repo.create_brief(web.conn, self.org_id, self.brand_id, {
            "source_kind": "manual", "source_ref": {},
            "product_id": product_id or self.product["id"],
            "coordinates": coordinates or {}, "visual_tone": None, "visual_concept": None,
            "style_key": "ugc", "request": {"parts": ["copy"], "copy_length": "short"},
        })
        reply = {
            "coordinates": {"proof": proof_label},
            "sets": [{"body": _cjk(140), "headline": _cjk(10), "description": _cjk(15)}
                     for _ in range(5)],
            "visual_tone": None, "visual_concept": "測試視覺概念", "warnings": [],
        }
        fake = providers.FakeProvider(response=providers.ProviderResponse(
            output_text=json.dumps(reply, ensure_ascii=False), structured=None,
            usage=providers.Usage(input_tokens=500, output_tokens=200), stop_reason="end_turn",
        ))
        workbench_jobs.PROVIDER = fake
        web.conn.commit()
        background_module.app().run_worker(wait=False)
        row = web.conn.execute(
            "SELECT body_json FROM workbench_output WHERE brief_id = %s AND part = 'copy'",
            (brief_id,),
        ).fetchone()
        assert row is not None
        return fake.calls[0]["messages"][0]["content"], row["body_json"]


class CopyPromptProofMenuTest(_CopyRunBase):
    def _coordinates_line(self, body: dict) -> str:
        return next(line for line in body["validation"] if "coordinates" in line)

    def test_no_evidence_offers_only_none_and_rejects_lab_report(self):
        prompt, body = self._run_copy("檢驗報告／認證")
        section = _proof_section(prompt)
        self.assertIn("- 無證明", section)
        for label in _PROOF_LABELS:
            self.assertNotIn(label, section)
        self.assertTrue(self._coordinates_line(body).startswith("❌"), body["validation"])

    def test_customer_review_fact_offers_customer_review(self):
        bi_repo.create_brand_fact(
            web.conn, self.brand_id, actor=ACTOR, fact_type="proof", fact_key="customer_review",
            label="顧客評論", value="「喝了一個月，下午不再昏沉。」——王小姐", status="confirmed",
            confirmed_by=ACTOR,
        )
        prompt, body = self._run_copy("顧客評論原話")
        section = _proof_section(prompt)
        self.assertIn("- 顧客評論原話", section)
        self.assertIn("- 無證明", section)
        self.assertNotIn("檢驗報告／認證", section)
        self.assertIn("喝了一個月，下午不再昏沉", prompt)  # the evidence text is quoted in
        self.assertTrue(self._coordinates_line(body).startswith("✅"), body["validation"])


class CopyPromptOfferCoordinateTest(_CopyRunBase):
    """F44-I01 (Contract B): the brief's offer coordinate decides which offer the copy prompt
    lists and what its 優惠 block asks for. The sell-way has its own list-price offer (`bundle`)
    under a 滿 NT$999 免運 store policy."""

    NONE_LINE = "這則廣告的優惠座標是無優惠：不寫任何優惠、優惠價或原價（售價可以寫）。"
    CARRY_LINE = "這則廣告要帶下面 [offer:…] 這個優惠：每一組文案都把它的原字句寫進標題或內文。"
    PRICE = "優惠價 NT$999（原價 NT$1,197）"  # F45: no product name
    SHIPPING = "滿 NT$999 免運"

    def setUp(self):
        super().setUp()
        bi_repo.save_brand_policies(
            web.conn, self.brand_id, [{"key": "ship_threshold", "params": {"threshold": 999}}],
            actor=ACTOR,
        )
        box = bi_repo.save_sell_way(
            web.conn, self.brand_id, name="單盒", actor=ACTOR, product_id=self.product["id"],
            economics={"selling_price": 399},
        )["id"]
        self.three = bi_repo.save_sell_way(
            web.conn, self.brand_id, name="三盒組", actor=ACTOR,
            components=[{"sell_way_id": box, "qty": 3}],
            economics={"selling_price": 999, "list_price": 1197,
                       "unit_variable_cost": 300, "shipping_cost": 60},
        )["id"]

    def _block(self, coordinates: dict) -> tuple[str, str]:
        prompt, _body = self._run_copy("無證明", product_id=self.three, coordinates=coordinates)
        return prompt, _offer_block(prompt)

    def test_no_offer_coordinate_by_label_lists_no_offer(self):
        prompt, block = self._block({"offer": "無優惠"})
        self.assertIn(self.NONE_LINE, block.split("\n"))
        self.assertNotIn("- [offer:", block)
        self.assertNotIn(self.CARRY_LINE, block)
        # The offer price and list price reach the prompt through this block only.
        self.assertNotIn("原價 NT$1,197", prompt)
        self.assertNotIn(self.SHIPPING, prompt)

    def test_offer_coordinate_by_key_lists_only_that_offer(self):
        _prompt, block = self._block({"offer": "bundle"})
        self.assertIn(self.CARRY_LINE, block.split("\n"))
        self.assertNotIn(self.NONE_LINE, block)
        self.assertIn(f"- [offer:bundle:{self.three}] {self.PRICE}", block)
        self.assertNotIn(self.SHIPPING, block)

    def test_brief_without_offer_coordinate_is_unchanged(self):
        _prompt, block = self._block({})
        self.assertIn(self.PRICE, block)
        self.assertIn(self.SHIPPING, block)
        self.assertNotIn(self.NONE_LINE, block)
        self.assertNotIn(self.CARRY_LINE, block)


class BriefTextDeadlineTest(unittest.TestCase):
    def test_deadline_line_when_handed_over(self):
        text = prompts.brief_text({
            "coordinates_snapshot_json": {"offer": "限時限量"},
            "request_json": {"offer_deadline": "2026-10-31"},
        }, "產品")
        self.assertIn(
            "限時截止日：2026-10-31（限時限量文案只能寫這一個日期，不得另造期限或數量）", text,
        )
        self.assertNotIn("寫無優惠版本", text)

    def test_no_offer_line_when_limited_time_without_deadline(self):
        for offer in ("限時限量", "limited_time"):
            with self.subTest(offer=offer):
                text = prompts.brief_text(
                    {"coordinates_snapshot_json": {"offer": offer}, "request_json": {}}, "產品",
                )
                self.assertIn("這組座標寫了限時限量但沒有截止日：寫無優惠版本，不提期限。", text)
                self.assertNotIn("限時截止日", text)

    def test_neither_line_for_other_offers(self):
        text = prompts.brief_text({"coordinates_snapshot_json": {"offer": "無優惠"}}, "產品")
        self.assertNotIn("限時", text)


if __name__ == "__main__":
    unittest.main()
