"""app/tests/test_schedule_diagnosis.py — 票 01（T6c）：成效判讀（後端）。

只寫全域 CLAUDE.md 測試四類允許的（資料正確性），三支，不多寫（ticket done-check 3 明文）：

1. `CompressionConservesMoneyTest`：`compress()` 印出來的每個維度，各列花費＋未標座標那列
   ＝ `total_spend`——壓縮層說謊等於後面全部白算。
2. `ConvergeDedupesTest`：兩個 lens 給同一個 `(dimension, coordinate_key, direction)`，
   `converge()` 只留一條、`agreed_by` 有兩個名字、`impact_spend` 取大的那個。
3. `BreakevenFallbackTest`：三層順序——有實際毛利率用實際；沒有但有規則卡用規則卡；
   兩者皆無回 `None`（絕不回 1.0）。
"""

import re
import unittest
from uuid import uuid4

import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import rule_cards
from app.core import settings as coresettings
from app.orders import repository as orders_repo
from app.schedule import creative as creative_mod
from app.schedule import diagnosis

_SPEND_CELL_RE = re.compile(r"^\|[^|]*\|\s*([\d,]+)\s*\|")


def _bucket(spend: float, *, roas=None, roas_conservative=None, coverage=1.0, ad_count=1) -> dict:
    return {
        "spend": spend, "impressions": 100, "clicks": 10, "revenue": None,
        "roas": roas, "roas_conservative": roas_conservative,
        "roas_coverage": coverage, "ad_count": ad_count,
    }


def _performance_fixture() -> dict:
    """跟 `performance.brand_creative_performance()` 同一個輸出形狀——每個維度自己的
    `values[].spend` ＋ `untagged.spend` 都等於這個幣別的 `total_spend`（1000）。刻意用整數
    金額：`compress()` 用 `{:,.0f}` 格式印出來，測試才能逐字解析回整數比對，不必擔心小數點
    捨入把守恆測試自己弄假紅。"""
    dimensions = [
        {
            "dimension": dim_key,
            "untagged": {"spend": 100.0, "ad_count": 1},
            "values": [
                {"key": "v1", "label": "座標甲", **_bucket(600.0, roas=2.0, roas_conservative=1.5)},
                {"key": "v2", "label": "座標乙", **_bucket(300.0, roas=1.0, roas_conservative=0.8)},
            ],
        }
        for dim_key in creative_mod.COORDINATE_KEYS
    ]
    return {
        "window": {"start_date": "2026-09-01", "end_date": "2026-09-30"},
        "currencies": [{
            "currency": "TWD", "total_spend": 1000.0,
            "untagged": {"spend": 100.0, "ad_count": 1}, "dimensions": dimensions,
        }],
    }


class CompressionConservesMoneyTest(unittest.TestCase):
    """壓縮層說謊等於後面全部白算：每個維度**印出來的文字**（含未標座標那一列）加總花費要
    等於 `total_spend`——不只是輸入資料本身守恆，是印出去給 agent 看的表格也要守恆，才防得住
    「表格印漏一列」這種不改資料、只改顯示就會出事的錯。"""

    def test_every_dimension_table_sums_to_total_spend(self):
        performance = _performance_fixture()
        total_spend = int(performance["currencies"][0]["total_spend"])
        text = diagnosis.compress(performance, (1.43, "規則卡毛利率 70%"))

        sections = text.split("\n## ")[1:]  # 第一段是幣別總覽，之後每段是一個維度
        self.assertEqual(len(sections), len(creative_mod.COORDINATE_KEYS))
        for section in sections:
            rows_spend = sum(
                int(match.group(1).replace(",", ""))
                for line in section.splitlines()
                if (match := _SPEND_CELL_RE.match(line)) is not None
            )
            self.assertEqual(
                rows_spend, total_spend,
                msg=f"維度區塊沒有加總到 total_spend：\n{section}",
            )


class ConvergeDedupesTest(unittest.TestCase):
    """去重鍵 `(dimension, coordinate_key, direction)`：同鍵只留一條，`agreed_by` 累加成
    名單，`impact_spend` 取大的那個——重複是信號不是雜訊（spec 新規則）。"""

    def test_two_lenses_agreeing_collapse_into_one_with_larger_impact_spend(self):
        outputs = [
            {"dimension": "audience", "coordinate_key": "cold_problem_aware",
             "coordinate_label": "陌生・知道問題", "direction": "scale_up",
             "impact_spend": 500.0, "headline": "受眾角度的說法", "evidence": "e1",
             "lens": "audience"},
            {"dimension": "audience", "coordinate_key": "cold_problem_aware",
             "coordinate_label": "陌生・知道問題", "direction": "scale_up",
             "impact_spend": 800.0, "headline": "預算角度的說法", "evidence": "e2",
             "lens": "budget"},
        ]
        result = diagnosis.converge(outputs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["impact_spend"], 800.0)
        self.assertEqual(result[0]["headline"], "預算角度的說法")  # 較大 impact_spend 那條的內文
        self.assertEqual(set(result[0]["agreed_by"]), {"audience", "budget"})


class BreakevenFallbackTest(unittest.TestCase):
    """三層順序——有實際毛利率用實際；沒有但有規則卡用規則卡；兩者皆無回 `None`
    （絕不回 1.0：1.0 等於宣稱毛利 100%，會把賠錢的座標畫成贏家）。三個品牌各自代表一層，
    互不干擾（一個 test 方法裡驗完三層，不拆成三支——ticket 明講只准三支測試）。"""

    def _new_brand(self, suffix: str) -> tuple[str, str]:
        org_id = f"org_diag_test_{suffix}_{uuid4().hex[:8]}"
        web.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (org_id, org_id),
        )
        web.conn.commit()
        brand_id = bi_repo.create_brand(
            web.conn, org_id=org_id, name=f"測試品牌{uuid4().hex[:6]}",
            client_name=None, actor="測試員",
        )["id"]
        return org_id, brand_id

    def test_breakeven_roas_falls_through_the_three_layers_in_order(self):
        # 層 2：沒有任何訂單、沒有登記任何 SKU 成本——規則卡尚未被使用者改過，用 CARDS 預設
        # 值 0.70（打平線 1÷0.70 ≈ 1.43）。
        org_2, brand_2 = self._new_brand("card_default")
        roas_2, source_2 = diagnosis.breakeven_roas(web.conn, org_2, brand_2)
        self.assertEqual(roas_2, 1.43)
        self.assertIn("規則卡", source_2)

        # 層 1：這個月官網訂單登記過 SKU 成本，算得出實際毛利率（60%），優先用它，不用規則卡。
        org_1, brand_1 = self._new_brand("actual_margin")
        month_start = coresettings.today_for_org(web.conn, org_id=org_1).replace(day=1)
        orders_repo.save_orders(
            web.conn, brand_1,
            [{
                "order_number": "O-DIAG-1", "order_date": month_start.isoformat(),
                "total_amount": 1000, "refunded_amount": 0, "financial_status": "paid",
                "fulfillment_status": "fulfilled", "order_status": "paid", "voucher_code": None,
                "billing_email": None, "billing_phone": None,
                "items": [{"sku": "SKU-DIAG", "item_price": 1000, "quantity": 1}],
            }],
            source="easystore_xlsx", actor="測試員",
        )
        orders_repo.set_sku_cost(web.conn, brand_1, "SKU-DIAG", 400, actor="測試員")  # 毛利 60%
        roas_1, source_1 = diagnosis.breakeven_roas(web.conn, org_1, brand_1)
        self.assertAlmostEqual(roas_1, round(1 / 0.6, 2), places=2)
        self.assertIn("官網訂單", source_1)

        # 層 3：兩層都算不出一個 >0 的毛利率（規則卡被使用者自己設成 0，沒有訂單）——絕不回
        # 1.0 頂著，誠實回 None。
        org_3, brand_3 = self._new_brand("nothing_usable")
        rule_cards.set_value(
            web.conn, brand_3, "gross_margin", "gross_margin_rate", 0.0,
            actor="測試員", org_id=org_3,
        )
        roas_3, _source_3 = diagnosis.breakeven_roas(web.conn, org_3, brand_3)
        self.assertIsNone(roas_3)
        self.assertNotEqual(roas_3, 1.0)


if __name__ == "__main__":
    unittest.main()
