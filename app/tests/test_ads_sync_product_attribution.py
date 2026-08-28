"""app/tests/test_ads_sync_product_attribution.py — 票 11 D3：Meta 同步的產品歸因。

獨立成檔而不是塞進 test_ads_sync.py：那個檔案已經頂到單檔行數上限（見
test_architecture_boundaries.py 的 FILE_LINE_CAP），加新測試類別會超標。共用夾具
（_BaseSyncTest／_campaign／_insight／ACTOR）直接從 test_ads_sync 匯入，不重寫一份
（比照 test_ads_product_cleanup.py 借用 test_ads_brand_cleanup._seed_table 的先例）。
"""


import app.main as main
from app.ads import sync as ads_sync
from app.brand_intelligence import repository as bi_repo
from app.core import db
from app.tests.test_ads_sync import ACTOR, _BaseSyncTest, _campaign, _insight


class ProductAttributionTest(_BaseSyncTest):
    """能確定產品才寫 product_id（鐵則 16：模稜兩可回 None），跟 CSV／模擬共用
    `performance.resolve_product_id`。"""

    def test_matched_ad_writes_its_packages_product_id(self):
        # 直接寫已 confirmed 的 external_ad_mapping：`_claimed_brand_for` 靠它就能解出
        # brand_id（見 sync.py），不必先跑一輪 discover→claim。
        resp = self.client.post(f"/api/campaigns/{self.bid}",
                                json={"budget": 10000, "objective": "sales"})
        cycle_id = resp.json()["cycle_id"]
        product = bi_repo.create_product(main.conn, self.bid, name="虛構商品", actor=ACTOR)
        pkg_id, ts = db.new_id("pkg"), db.now_utc()
        main.conn.execute(
            "INSERT INTO publishing_package (id, org_id, brand_id, campaign_cycle_id,"
            " product_id, campaign_name, adset_name, ad_name, destination_url, utm_json,"
            " status, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '{}', 'ready', %s)",
            (pkg_id, db.DEV_ORG_ID, self.bid, cycle_id, product["id"], "測試活動", "測試組合",
             "廣告一", "https://example.test", ts),
        )
        main.conn.execute(
            "INSERT INTO external_ad_mapping (id, org_id, brand_id, publishing_package_id,"
            " campaign_cycle_id, platform, meta_campaign_id, meta_ad_id, claim_status,"
            " confirmed_by, confirmed_at, created_at) VALUES (%s, %s, %s, %s, %s, 'meta', '980',"
            " 'ad_prod_980', 'confirmed', %s, %s, %s)",
            (db.new_id("eam"), db.DEV_ORG_ID, self.bid, pkg_id, cycle_id, ACTOR, ts, ts),
        )
        main.conn.commit()

        self._sync(campaigns=[_campaign("980", f"{self.brand_name}_20260805_sales")],
                  insights=[_insight("980", ad_id="ad_prod_980")])
        row = main.conn.execute(
            "SELECT product_id FROM performance_snapshot WHERE meta_ad_id = 'ad_prod_980'"
        ).fetchone()
        self.assertEqual(row["product_id"], product["id"])

    def test_unmatched_ad_leaves_product_id_null(self):
        """對不到 publishing_package、檔期也沒有唯一產品可以退回時留白，匯入照樣成功。"""
        self._sync(campaigns=[_campaign("981", f"{self.brand_name}_20260806_sales")],
                  insights=[_insight("981", ad_id="ad_prod_981")])
        discovered_id = main.conn.execute(
            "SELECT id FROM discovered_campaign WHERE meta_campaign_id = '981'"
        ).fetchone()["id"]
        ads_sync.claim(main.conn, self.bid, discovered_id, ACTOR)
        result = self._sync(campaigns=[_campaign("981", f"{self.brand_name}_20260806_sales")],
                            insights=[_insight("981", ad_id="ad_prod_981")])
        self.assertEqual(result.snapshots, 1)
        row = main.conn.execute(
            "SELECT product_id FROM performance_snapshot WHERE meta_ad_id = 'ad_prod_981'"
        ).fetchone()
        self.assertIsNone(row["product_id"])
