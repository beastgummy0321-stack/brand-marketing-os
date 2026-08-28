"""app/tests/test_ads_creative_theme_repoint.py — 票 02-repoint-creative-readers。

驗收規格（.scratch/adloop/tickets/02-repoint-creative-readers.md）「如何知道做完了」
第 1–4 點：一期有已採用主題時，交貨確認、交接包組裝、反回音室候選、法務掃描
四條下游路徑要能看到真的資料——不再是「素材還在準備中」的空殼。

資料建置一律走 theme_repository（`create_theme` + `adopt_theme`），比照
app/tests/test_ads_creative_theme.py 的既有作法；不新建一套 harness。
"""

import unittest

from app.ads import compliance, creative, delivery, handoff, nextcycle
from app.ads import repository as ads_repo
from app.ads import theme_repository as theme_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db

ACTOR = "測試員"

_FINGERPRINT = {"angle": "benefit", "tone": "warm", "format": "single_image",
                "selling_point": "quality"}


class _Base(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.brand = bi_repo.create_brand(self.conn, name="虛構晨光咖啡（重接票）",
                                          client_name="測試客戶", actor=ACTOR, org_id=db.DEV_ORG_ID)
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
            (self.cell_id, db.DEV_ORG_ID, self.cycle_id, self.bid, self.product_id, "晨間第一杯", db.now_iso()),
        )
        self.conn.commit()

        # 一顆已採用主題，底下三個元件（標題／文案／圖片提示詞）——文案裡刻意埋一個
        # 內建法定紅線詞（「療效」），供第 4 點法務掃描斷言用（app/ads/compliance_wordlist.py）。
        self.theme = theme_repo.create_theme(
            self.conn, self.bid, campaign_cycle_id=self.cycle_id,
            experiment_cell_id=self.cell_id, format_key="single_image",
            name="晨光第一杯主題", folder_code="R1P0", actor=ACTOR,
            components=[
                {"component_type": "title", "content": "早晨從一杯開始",
                 "fingerprint_json": _FINGERPRINT},
                {"component_type": "body", "content": "本產品有神奇療效，一杯見效",
                 "fingerprint_json": _FINGERPRINT},
                {"component_type": "image_prompt", "content": "暖金色晨光下的咖啡杯特寫"},
            ],
        )
        theme_repo.adopt_theme(self.conn, self.bid, self.theme["id"], actor=ACTOR)


class DeliveryViewSeesAdoptedThemeTest(_Base):
    """驗收 1：delivery.view() 不再卡在 assembling，一個已採用主題對一則交貨項目。"""

    def test_view_status_is_not_assembling_with_one_item_per_adopted_theme(self):
        result = delivery.view(self.conn, self.bid, self.cycle_id)
        self.assertNotEqual(result["status"], "assembling", result)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["id"], self.cell_id)
        self.assertTrue(result["items"][0]["copy"])
        self.assertTrue(result["items"][0]["image_prompt"])


class HandoffBuildPackagesWritesRowsTest(_Base):
    """驗收 2：handoff.build_packages() 寫出非零份交接包（連帶證明 DEC-A：hook_id／
    copy_variant_id 存 cthc_* 主題元件 id 不再被外鍵擋下）。"""

    def test_build_packages_writes_nonzero_rows_with_theme_component_ids(self):
        count = handoff.build_packages(self.conn, self.bid, self.cycle_id, ACTOR)
        self.assertGreater(count, 0)

        rows = [dict(r) for r in self.conn.execute(
            "SELECT * FROM publishing_package WHERE brand_id = %s AND campaign_cycle_id = %s",
            (self.bid, self.cycle_id),
        )]
        self.assertEqual(len(rows), count)
        row = rows[0]
        self.assertTrue(row["hook_id"] and row["hook_id"].startswith("cthc_"))
        self.assertTrue(row["copy_variant_id"] and row["copy_variant_id"].startswith("cthc_"))

        packages = handoff.list_packages(self.conn, self.bid, self.cycle_id)
        self.assertEqual(packages[0]["hook_text"], "早晨從一杯開始")
        self.assertEqual(packages[0]["copy_text"], "本產品有神奇療效，一杯見效")


class EchoChamberCandidatesNonEmptyTest(_Base):
    """驗收 3：nextcycle 反回音室比對用的候選指紋清單（經 creative.list_variants()）非空。"""

    def test_candidate_fingerprints_are_non_empty(self):
        candidates = [v["fingerprint"] for v in creative.list_variants(self.conn, self.bid, self.cycle_id)
                      if not v["rejected"] and v["fingerprint"]]
        self.assertTrue(candidates)
        self.assertIn(_FINGERPRINT, candidates)
        # check_echo_chamber() 本身在沒有歷史採用素材可比對時誠實回 None（不是誤判「太像」），
        # 但這裡要驗的是它賴以運作的候選清單來源本身不再是空的。
        self.assertIsNone(nextcycle.check_echo_chamber(self.conn, self.bid, self.cycle_id))


class ComplianceScanSeesAdoptedComponentsTest(_Base):
    """驗收 4：compliance.scan_cycle() 掃到已採用主題的元件，埋的禁用字產生命中。"""

    def test_planted_banned_term_produces_a_finding(self):
        findings = compliance.scan_cycle(self.conn, self.bid, self.cycle_id)
        self.assertTrue(findings)
        hit = next((f for f in findings if "療效" in f.message), None)
        self.assertIsNotNone(hit, [f.message for f in findings])
        self.assertEqual(hit.evidence["source_category"], "law")


if __name__ == "__main__":
    unittest.main()
