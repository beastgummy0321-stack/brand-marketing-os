"""app/tests/test_schedule_performance.py — 票 T5（ADR 0057）：花費透過深度 3 綁定接上
七維座標。

只寫全域 CLAUDE.md 測試四類允許的（金額／資料正確性——這整張票就是一個金額對帳的問題）：

1. `untagged.spend` ＋ 逐維度 `values[].spend` 加總永遠等於 `total_spend`——逐維度、逐幣別
   都成立（ticket done-check 1；矛盾檢查段裁決：`untagged` 是逐維度一份，不是逐幣別一份）。
   `total_spend` 本身等於 `meta_entity_spend` 這批帳號、`level='ad'`、這個窗口的花費原始
   總和（不是繞了一圈算出來的另一個數字）。
2. 兩個幣別各自一份 `currencies` 條目，沒有任何欄位把兩邊加在一起（done-check 2）。
3. `roas` 覆蓋率誠實：一個座標值底下的花費列，只有追蹤到 `roas` 的那幾列才進 `revenue`／
   `roas`，覆蓋率是「追蹤到的列數 / 全部列數」，不是全部平均、也不是因為某幾天沒追蹤就讓
   整組回 None（done-check 3；ADR 0057 §7 明講不能重用 `spend_summary` 的 `bool_and` 規則）。
4. 改名不會悄悄轉嫁金額：綁定當下的節點名字跟現在這棵樹的名字對不上，這筆錢要落進
   `untagged`，不能繼續掛在舊候選的座標下面（done-check 5；ADR 0055 §4 的讀時否決票）。

不透過 HTTP／`require_actor`：這裡驗的是 `performance.brand_creative_performance()` 這支
純讀取函式本身的算法，跟 `test_meta_daily_spend.py` 的 `LevelNeverSumsTest`／`CpaMappingTest`
同一個既有慣例——直接呼叫、不架 `TestClient`。租戶隔離已經是
`test_org_isolation_all_tables.py`／`UnscopedTenantReadScanTest` 的範圍（ticket 明講這一條
由那道機器閘門守住），這裡不重寫一份。
"""

import json
import unittest
from datetime import date, timedelta
from uuid import uuid4

import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import settings as coresettings
from app.meta import repository as meta_repo
from app.schedule import performance
from app.schedule import repository as schedule_repo


def _tree_fenced(nodes: list, budget_level: int = 2) -> str:
    payload = {
        "levels": ["行銷活動", "廣告組合", "廣告"], "budget_level": budget_level, "nodes": nodes,
    }
    return f"活動樹。\n\n```json\n{json.dumps(payload, ensure_ascii=False)}\n```"


def _leaf(name: str) -> dict:
    return {"name": name, "fields": [], "share": None, "warnings": [], "children": []}


def _branch(name: str, share: float, leaf_name: str) -> dict:
    return {
        "name": name, "fields": [], "share": share, "warnings": [],
        "children": [_leaf(leaf_name)],
    }


def _two_path_tree(leaf_a: str = "單元1", leaf_b: str = "單元2") -> list:
    """兩條路徑到底的三層樹：depth-3 node_key 分別是 1.1.1／1.2.1——夠這個檔案的測試用，
    不需要 `test_schedule.py` 那批分岔／改名的樹形。"""
    return [{
        "name": "活動一", "fields": [], "share": None, "warnings": [],
        "children": [_branch("組合1", 0.5, leaf_a), _branch("組合2", 0.5, leaf_b)],
    }]


class _PerformanceTestBase(unittest.TestCase):
    def _make_org(self, suffix: str) -> str:
        org_id = f"org_perf_test_{suffix}_{uuid4().hex[:10]}"
        web.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (org_id, org_id),
        )
        web.conn.commit()
        return org_id

    def _make_brand(self, org_id: str) -> str:
        return bi_repo.create_brand(
            web.conn, org_id=org_id, name=f"測試品牌{uuid4().hex[:6]}",
            client_name=None, actor="測試員",
        )["id"]

    def _connect_and_bind_account(
        self, org_id: str, brand_id: str, account_id: str, *, currency: str = "TWD",
    ) -> str:
        meta_repo.save_token(web.conn, org_id, "tok")
        meta_repo.upsert_accounts(web.conn, org_id, [
            {"account_id": account_id, "name": account_id, "currency": currency},
        ])
        web.conn.commit()
        local_id = next(
            a["id"] for a in meta_repo.list_accounts(web.conn, org_id)
            if a["account_id"] == account_id
        )
        meta_repo.bind(web.conn, org_id, brand_id, local_id)
        web.conn.commit()
        return local_id

    def _seed_ad_spend(self, org_id: str, local_account_id: str, ad_id: str, day: date, *,
                        spend: float, impressions: int = 100, clicks: int = 10,
                        roas: float | None = None) -> None:
        meta_repo.upsert_entity_spend(web.conn, org_id, local_account_id, [{
            "level": "ad", "entity_id": ad_id, "entity_name": ad_id,
            "campaign_id": "camp-x", "adset_id": "as-x", "ad_id": ad_id,
            "spend_date": day, "spend": spend, "impressions": impressions, "clicks": clicks,
            "roas": roas, "actions": None, "action_values": None,
            "attribution_window": "7d_click,1d_view",
        }])
        web.conn.commit()

    def _insert_succeeded_tree_row(self, org_id: str, brand_id: str, nodes: list, *,
                                    daily_budget: float = 1000.0) -> str:
        row_id = coredb.new_id("llm")
        web.conn.execute(
            "INSERT INTO llm_task (id, org_id, brand_id, task_type, context_scope_json,"
            " input_context_ids_json, input_context_hash, knowledge_item_ids_json,"
            " brand_version, prompt_template_id, prompt_template_version, provider, model,"
            " status, attempt_no, started_at, rendered_output, finished_at)"
            " VALUES (%s, %s, %s, 'schedule_tree', %s, '[]', '', '[]', 1, 'p', 'v1', 'seed',"
            " 'seed', 'succeeded', 1, %s, %s, %s)",
            (row_id, org_id, brand_id,
             coredb.jsonb({"daily_budget": daily_budget, "plan_index": 0}),
             coredb.now_iso(), _tree_fenced(nodes), coredb.now_iso()),
        )
        web.conn.commit()
        return row_id

    def _bind_ad(self, org_id: str, brand_id: str, node_key: str, node_name: str,
                 external_id: str, source_tree_task_id: str) -> None:
        channel_id = schedule_repo.ensure_meta_channel(web.conn, org_id)
        schedule_repo.upsert_binding(
            web.conn, org_id=org_id, brand_id=brand_id, channel_id=channel_id,
            node_key=node_key, node_name_at_bind=node_name, external_id=external_id,
            external_status="ACTIVE", source_tree_task_id=source_tree_task_id,
        )
        web.conn.commit()

    def _set_binding_created_at(self, org_id: str, brand_id: str, node_key: str,
                                 source_tree_task_id: str, day: date) -> None:
        """票 10（ADR 0064 §2）：日期歸屬看的是 `channel_entity_map.created_at`，
        `upsert_binding()` 自己不收這個參數（一律 `now()`）——測試要控制「這次綁定是哪一天
        生效的」，只能像這樣直接改那一列，不是呼叫端該有的介面。"""
        web.conn.execute(
            "UPDATE channel_entity_map SET created_at = %s"
            " WHERE org_id = %s AND brand_id = %s AND node_key = %s"
            " AND source_tree_task_id = %s",
            (day, org_id, brand_id, node_key, source_tree_task_id),
        )
        web.conn.commit()

    def _tag_ad(self, org_id: str, brand_id: str, source_tree_task_id: str, node_key: str,
                coordinates: dict) -> None:
        """跟 `binding._bind_ad` 對應的那個廣告位置，寫一輪候選——七個維度缺席的一律
        `None`（`persist_creative_result` 的 `_resolve_coordinates` 只認 `brand_coordinate`
        已經有的 label，呼叫端要先用 `schedule_repo.create_coordinate()` 造好）。"""
        full = {"audience": None, "pain": None, "angle": None, "hook": None,
                "proof": None, "offer": None, "format": None}
        full.update(coordinates)
        schedule_repo.persist_creative_result(
            web.conn, org_id, brand_id, task_id=coredb.new_id("llm"),
            source_tree_task_id=source_tree_task_id,
            ads=[{"node_key": node_key, "coordinates": full, "visual_tone": None,
                  "visual_concept": None, "fields": [{"label": "文案", "value": ["測試"]}]}],
        )

    def _month_start(self, org_id: str) -> date:
        return coresettings.today_for_org(web.conn, org_id=org_id).replace(day=1)


class MoneyInvariantTest(_PerformanceTestBase):
    """done-check 1／2：untagged + Σvalues == total，逐維度逐幣別都成立；兩個幣別互不相加。"""

    def test_untagged_plus_values_equals_total_for_every_dimension_and_currency(self):
        org_id = self._make_org("invariant")
        brand_id = self._make_brand(org_id)
        account_id = self._connect_and_bind_account(org_id, brand_id, "act-1")
        day = self._month_start(org_id)

        tree_task_id = self._insert_succeeded_tree_row(org_id, brand_id, _two_path_tree())
        schedule_repo.create_coordinate(web.conn, org_id, brand_id, "pain", "怕買到假貨", None)

        # ad-1：綁定在 1.1.1、標了 pain 座標。ad-2：完全沒綁定（今天的真實狀態：手動建的
        # 廣告，不在任何座標之下）。
        self._seed_ad_spend(org_id, account_id, "ad-1", day, spend=300.0)
        self._seed_ad_spend(org_id, account_id, "ad-2", day, spend=700.0)
        self._bind_ad(org_id, brand_id, "1.1.1", "單元1", "ad-1", tree_task_id)
        self._tag_ad(org_id, brand_id, tree_task_id, "1.1.1", {"pain": "怕買到假貨"})

        result = performance.brand_creative_performance(web.conn, org_id, brand_id)
        self.assertEqual(len(result["currencies"]), 1)
        currency = result["currencies"][0]
        self.assertEqual(currency["currency"], "TWD")

        expected_total = web.conn.execute(
            "SELECT COALESCE(SUM(spend), 0) AS s FROM meta_entity_spend"
            " WHERE org_id = %s AND ad_account_id = %s AND level = 'ad'",
            (org_id, account_id),
        ).fetchone()["s"]
        self.assertAlmostEqual(currency["total_spend"], float(expected_total), places=2)
        self.assertAlmostEqual(currency["total_spend"], 1000.0, places=2)

        self.assertEqual(len(currency["dimensions"]), 7)
        for dim in currency["dimensions"]:
            values_spend = sum(v["spend"] for v in dim["values"])
            self.assertAlmostEqual(
                dim["untagged"]["spend"] + values_spend, currency["total_spend"], places=2,
                msg=f"維度 {dim['dimension']} 的 untagged + values 沒有對到 total_spend",
            )

        pain = next(d for d in currency["dimensions"] if d["dimension"] == "pain")
        self.assertEqual(len(pain["values"]), 1)
        self.assertAlmostEqual(pain["values"][0]["spend"], 300.0, places=2)
        self.assertEqual(pain["values"][0]["label"], "怕買到假貨")
        self.assertAlmostEqual(pain["untagged"]["spend"], 700.0, places=2)

        # ad-1 沒有其餘六個維度的座標——那六個維度全部落在 untagged。
        for dim in currency["dimensions"]:
            if dim["dimension"] == "pain":
                continue
            self.assertEqual(dim["values"], [])
            self.assertAlmostEqual(dim["untagged"]["spend"], 1000.0, places=2)

    def test_two_currencies_stay_separate_and_nothing_sums_them(self):
        org_id = self._make_org("two_currency")
        brand_id = self._make_brand(org_id)
        twd_account = self._connect_and_bind_account(org_id, brand_id, "act-twd", currency="TWD")
        usd_account = self._connect_and_bind_account(org_id, brand_id, "act-usd", currency="USD")
        day = self._month_start(org_id)
        self._seed_ad_spend(org_id, twd_account, "ad-twd", day, spend=1000.0)
        self._seed_ad_spend(org_id, usd_account, "ad-usd", day, spend=50.0)

        result = performance.brand_creative_performance(web.conn, org_id, brand_id)
        self.assertEqual(set(result.keys()), {"window", "currencies"})  # 沒有第三個「總計」欄位
        self.assertEqual(len(result["currencies"]), 2)
        by_currency = {c["currency"]: c for c in result["currencies"]}
        self.assertEqual(set(by_currency), {"TWD", "USD"})
        self.assertAlmostEqual(by_currency["TWD"]["total_spend"], 1000.0, places=2)
        self.assertAlmostEqual(by_currency["USD"]["total_spend"], 50.0, places=2)


class RoasHonestyTest(_PerformanceTestBase):
    """done-check 3：一個座標值底下 15 列裡只有 2 列有 roas——revenue／roas 只算那 2 列，
    coverage 誠實回 2/15，不是 null、不是對 15 列取平均。"""

    def test_roas_coverage_and_revenue_use_only_tracked_rows(self):
        org_id = self._make_org("roas_honesty")
        brand_id = self._make_brand(org_id)
        account_id = self._connect_and_bind_account(org_id, brand_id, "act-1")
        month_start = self._month_start(org_id)

        tree_task_id = self._insert_succeeded_tree_row(org_id, brand_id, _two_path_tree())
        schedule_repo.create_coordinate(web.conn, org_id, brand_id, "pain", "怕買到假貨", None)
        self._bind_ad(org_id, brand_id, "1.1.1", "單元1", "ad-1", tree_task_id)
        self._tag_ad(org_id, brand_id, tree_task_id, "1.1.1", {"pain": "怕買到假貨"})

        for i in range(15):
            day = month_start + timedelta(days=i)
            roas = 2.0 if i == 0 else (4.0 if i == 1 else None)
            self._seed_ad_spend(org_id, account_id, "ad-1", day, spend=100.0, roas=roas)

        result = performance.brand_creative_performance(web.conn, org_id, brand_id)
        pain = next(
            d for d in result["currencies"][0]["dimensions"] if d["dimension"] == "pain"
        )
        value = pain["values"][0]
        self.assertAlmostEqual(value["roas_coverage"], 2 / 15, places=6)
        self.assertIsNotNone(value["revenue"])
        self.assertAlmostEqual(value["revenue"], 100.0 * 2.0 + 100.0 * 4.0, places=2)
        self.assertAlmostEqual(value["roas"], (200.0 + 400.0) / (100.0 + 100.0), places=4)
        self.assertAlmostEqual(value["spend"], 1500.0, places=2)  # 15 天全部的花費，不是只算 2 天


class PreviousTreeKeepsItsCoordinatesTest(_PerformanceTestBase):
    """done-check 1（ADR 0064 §1，取代 `RenamedNodeUntaggedTest`）：這支測試以前守的規則
    正是這張票要關掉的洞——綁定當下的節點名字跟現在這棵樹的名字對不上，就把舊候選的錢
    打進 untagged。實測（drill，3/3 組織）：規劃下一期之後，上一期花的錢永久失去座標。
    新規則：一列 `channel_entity_map` 自己名著它是哪一棵樹綁的，不再問「還跟現在最新那
    棵樹的名字對得上嗎」，所以重新展開、綁一個新的廣告在同一個位置，並不會讓上一棵樹
    綁的那支廣告的座標消失。`git stash` 掉這張票的原始碼改動，這支測試要紅（drill 的
    3/3 失敗）。"""

    def test_previous_tree_keeps_its_coordinates_after_the_next_tree_is_bound(self):
        org_id = self._make_org("prev_tree")
        brand_id = self._make_brand(org_id)
        account_id = self._connect_and_bind_account(org_id, brand_id, "act-1")
        day = self._month_start(org_id)

        tree_a = self._insert_succeeded_tree_row(
            org_id, brand_id, _two_path_tree(leaf_a="單元1")
        )
        schedule_repo.create_coordinate(web.conn, org_id, brand_id, "pain", "怕買到假貨", None)
        schedule_repo.create_coordinate(web.conn, org_id, brand_id, "pain", "怕太貴", None)
        self._bind_ad(org_id, brand_id, "1.1.1", "單元1", "ad-1", tree_a)
        self._tag_ad(org_id, brand_id, tree_a, "1.1.1", {"pain": "怕買到假貨"})
        self._seed_ad_spend(org_id, account_id, "ad-1", day, spend=500.0)

        # 重新展開：同一個位置（node_key "1.1.1"）改名，這是新一期的樹；照樹綁一支新的
        # 廣告 ad-2，一樣在 1.1.1，標上不同的 pain 座標。
        tree_b = self._insert_succeeded_tree_row(
            org_id, brand_id, _two_path_tree(leaf_a="單元1（改版）")
        )
        self._bind_ad(org_id, brand_id, "1.1.1", "單元1（改版）", "ad-2", tree_b)
        self._tag_ad(org_id, brand_id, tree_b, "1.1.1", {"pain": "怕太貴"})
        self._seed_ad_spend(org_id, account_id, "ad-2", day, spend=300.0)

        result = performance.brand_creative_performance(web.conn, org_id, brand_id)
        currency = result["currencies"][0]
        self.assertAlmostEqual(currency["untagged"]["spend"], 0.0, places=2)
        pain = next(d for d in currency["dimensions"] if d["dimension"] == "pain")
        self.assertAlmostEqual(pain["untagged"]["spend"], 0.0, places=2)
        values_by_label = {v["label"]: v["spend"] for v in pain["values"]}
        self.assertEqual(len(pain["values"]), 2)
        self.assertAlmostEqual(values_by_label["怕買到假貨"], 500.0, places=2)
        self.assertAlmostEqual(values_by_label["怕太貴"], 300.0, places=2)


class SpendMeetsTheBindingLiveOnItsDateTest(_PerformanceTestBase):
    """done-check 2（ADR 0064 §2，money）：一個平台實體被兩棵樹各綁過一次（同一支活動
    被下一期重新沿用），花費要按日期分派給那天已經生效的最新一次綁定——不能因為同一個
    `entity_id` 出現兩次綁定就整批算給某一邊，也不能兩邊都算（雙重計算）。"""

    def test_spend_before_and_after_the_second_binding_splits_by_date(self):
        org_id = self._make_org("date_split")
        brand_id = self._make_brand(org_id)
        account_id = self._connect_and_bind_account(org_id, brand_id, "act-1")
        month_start = self._month_start(org_id)
        day2 = month_start + timedelta(days=1)
        day12 = month_start + timedelta(days=11)

        schedule_repo.create_coordinate(web.conn, org_id, brand_id, "pain", "怕買到假貨", None)
        schedule_repo.create_coordinate(web.conn, org_id, brand_id, "pain", "怕太貴", None)

        # 綁定一：第 1 天綁的（tree A），標 pain=怕買到假貨。
        tree_a = self._insert_succeeded_tree_row(org_id, brand_id, _two_path_tree())
        self._bind_ad(org_id, brand_id, "1.1.1", "單元1", "ad-1", tree_a)
        self._set_binding_created_at(org_id, brand_id, "1.1.1", tree_a, month_start)
        self._tag_ad(org_id, brand_id, tree_a, "1.1.1", {"pain": "怕買到假貨"})

        # 綁定二：第 10 天綁的（tree B，同一個平台實體 ad-1 被下一期重新沿用），標
        # pain=怕太貴。
        tree_b = self._insert_succeeded_tree_row(org_id, brand_id, _two_path_tree())
        self._bind_ad(org_id, brand_id, "1.1.1", "單元1", "ad-1", tree_b)
        self._set_binding_created_at(
            org_id, brand_id, "1.1.1", tree_b, month_start + timedelta(days=9),
        )
        self._tag_ad(org_id, brand_id, tree_b, "1.1.1", {"pain": "怕太貴"})

        # 第 2 天花的錢在綁定二生效之前，屬於綁定一；第 12 天在綁定二生效之後，屬於它。
        self._seed_ad_spend(org_id, account_id, "ad-1", day2, spend=200.0)
        self._seed_ad_spend(org_id, account_id, "ad-1", day12, spend=300.0)

        result = performance.brand_creative_performance(web.conn, org_id, brand_id)
        currency = result["currencies"][0]
        self.assertAlmostEqual(currency["total_spend"], 500.0, places=2)
        self.assertAlmostEqual(currency["untagged"]["spend"], 0.0, places=2)
        pain = next(d for d in currency["dimensions"] if d["dimension"] == "pain")
        values_by_label = {v["label"]: v["spend"] for v in pain["values"]}
        self.assertAlmostEqual(values_by_label["怕買到假貨"], 200.0, places=2)
        self.assertAlmostEqual(values_by_label["怕太貴"], 300.0, places=2)
        # 沒有算兩次：兩個座標值加上 untagged 剛好等於 total_spend。
        self.assertAlmostEqual(
            pain["untagged"]["spend"] + sum(values_by_label.values()),
            currency["total_spend"], places=2,
        )
