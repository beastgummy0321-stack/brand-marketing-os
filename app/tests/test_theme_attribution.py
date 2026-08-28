"""app/tests/test_theme_attribution.py — 票 12-attribution-adjust：D 段歸因調整。

全程假 Meta API／假 LLM Provider，不發任何真實網路請求。品牌與產品名一律虛構。

精簡版：不開新表存歷史快照，直接在既有 creative_theme_component 加欄位存「最新一次
同步」的成效，每次同步覆蓋舊值（app/ads/migrations/0016_theme_component_performance.sql）。

驗收對應：
1. breakdown 資料覆蓋寫回主題元件；image_asset 不出現在請求。
2. 文字不一致 → 自動重打指紋＋更新存檔＋留一筆稽核；一致 → 零動作。
3. 重打指紋走引擎入口（無狀態：文字進、指紋出），不在同步碼裡手刻。
4. 元件成效端點回相對排名所需資料，不提供絕對值對帳介面。
"""

import json
import unittest

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import (
    meta_api,  # noqa: E402
    theme_attribution,  # noqa: E402
    theme_engine,  # noqa: E402
)
from app.ads import repository as ads_repo  # noqa: E402
from app.ads import sync as ads_sync  # noqa: E402
from app.ads import theme_repository as theme_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import settings as coresettings  # noqa: E402
from app.core.db import DEV_ORG_ID, new_id, now_iso  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402

ACTOR = "測試員"
ACCOUNT = "act_9988776655"


def _breakdown(ad_id="ad1", *, body=None, title=None, description=None, **overrides):
    data = dict(ad_id=ad_id, date_start="2026-08-01", date_stop="2026-08-07",
               impressions=1000, clicks=50, spend=100.0, conversions=2.0, revenue=400.0,
               body_asset=body, title_asset=title, description_asset=description)
    data.update(overrides)
    return meta_api.ComponentBreakdownRow(**data)


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        coresettings.set_setting(main.conn, "intake_budget_limit", "1000")
        coresettings.set_setting(main.conn, ads_sync.ACCOUNT_SETTING, ACCOUNT)
        coresettings.set_setting(main.conn, ads_sync.TOKEN_SETTING, "fake-token")
        self.brand = bi_repo.create_brand(
            main.conn, name=f"虛構晨光咖啡（歸因{abs(hash(self.id())) % 10000}）",
            client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        self.product_id = bi_repo.create_product(main.conn, self.bid, name="虛構濾掛組",
                                                  actor=ACTOR)["id"]
        self._orig_provider = theme_engine.PROVIDER

    def tearDown(self):
        theme_engine.PROVIDER = self._orig_provider
        coresettings.set_setting(main.conn, "intake_budget_limit", "30")

    def _swap_provider(self, reply: dict) -> FakeProvider:
        response = ProviderResponse(
            output_text=json.dumps(reply, ensure_ascii=False), structured=None,
            usage=Usage(input_tokens=100, output_tokens=50), stop_reason="end_turn")
        provider = FakeProvider(response=response)
        theme_engine.PROVIDER = provider
        return provider

    def _make_theme(self, *, components: list) -> dict:
        """開一個核准的檔期＋切角格＋主題（含指定元件），回傳 theme dict。"""
        cycle = ads_repo.create_cycle(main.conn, self.bid, product_ids=[self.product_id],
                                      pain_value=5, objective="sales", actor=ACTOR)
        cycle_id = cycle["id"]
        cell_id = new_id("exc")
        main.conn.execute(
            "INSERT INTO experiment_cell (id, org_id, campaign_cycle_id, brand_id, product_id,"
            " creative_angle, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (cell_id, DEV_ORG_ID, cycle_id, self.bid, self.product_id, "測試切角", now_iso()),
        )
        main.conn.commit()
        theme = theme_repo.create_theme(
            main.conn, self.bid, campaign_cycle_id=cycle_id, experiment_cell_id=cell_id,
            format_key="single_image", name="測試主題", folder_code="ABCD", actor=ACTOR,
            components=components,
        )
        return theme

    def _map_ad(self, cycle_id: str) -> str:
        """幫一支這次測試專用的 Meta 廣告接上檔期歸屬（比照 test_ads_sync.py I1 先例），
        回傳它的 ad_id。每次呼叫配一個新 id——sync.py 的 `_claimed_brand_for`／`_cycle_for`
        用 meta_ad_id 全域查詢（比照真實 Meta 廣告 id 全域唯一的假設），跨測試重複使用
        同一個字面值會讓查詢撞到別的測試留下的列。"""
        ad_id = new_id("ad")
        ts = now_iso()
        main.conn.execute(
            "INSERT INTO external_ad_mapping (id, org_id, brand_id, campaign_cycle_id, platform,"
            " meta_ad_id, claim_status, confirmed_by, confirmed_at, created_at) VALUES"
            " (%s, %s, %s, %s, 'meta', %s, 'confirmed', %s, %s, %s)",
            (new_id("eam"), DEV_ORG_ID, self.bid, cycle_id, ad_id, ACTOR, ts, ts),
        )
        main.conn.commit()
        return ad_id

    def _sync(self, *, component_breakdowns=None, client_cls=meta_api.FakeMetaClient):
        # today 選在單一月份的月底：預設 30 天回溯窗（_month_windows）才不會跨月切成兩塊
        # ——FakeMetaClient 不看日期篩選，跨月會讓假資料被 extend 兩次，重複計數
        # （比照 app/tests/test_ads_sync.py 既有測試一律選在月底的同款理由）。
        client = client_cls(component_breakdowns=component_breakdowns)
        return ads_sync.sync_account(main.conn, ACTOR, client=client, today="2026-08-31")


class RequestShapeTest(unittest.TestCase):
    """驗收 1 後半：image_asset 不出現在請求。"""

    def test_component_breakdowns_constant_excludes_image_asset(self):
        self.assertEqual(set(meta_api.COMPONENT_BREAKDOWNS), {"body_asset", "title_asset",
                                                                "description_asset"})
        self.assertNotIn("image_asset", meta_api.COMPONENT_BREAKDOWNS)

    def test_list_component_breakdowns_request_omits_image_asset_and_incompatible_fields(self):
        client = meta_api.MetaClient("fake-token")
        captured = {}

        def _fake_get(path, params):
            captured.update(params)
            return {"data": []}

        client._get = _fake_get
        client.list_component_breakdowns("act_1", "2026-08-01", "2026-08-07")
        self.assertEqual(captured["breakdowns"], "body_asset,title_asset,description_asset")
        self.assertNotIn("image_asset", captured["breakdowns"])
        self.assertNotIn("frequency", captured["fields"])

    def test_parse_component_breakdown_row_reads_asset_dicts(self):
        row = meta_api.parse_component_breakdown_row({
            "ad_id": "ad9", "date_start": "2026-08-01", "date_stop": "2026-08-07",
            "impressions": "500", "clicks": "20", "spend": "80.5",
            "actions": [{"action_type": "purchase", "value": "1"}],
            "action_values": [{"action_type": "purchase", "value": "300"}],
            "body_asset": {"id": "a1", "text": "文案內容"},
        })
        self.assertEqual(row.ad_id, "ad9")
        self.assertEqual(row.body_asset, {"id": "a1", "text": "文案內容"})
        self.assertIsNone(row.title_asset)
        self.assertEqual(row.conversions, 1.0)
        self.assertEqual(row.revenue, 300.0)


class RecordAndMatchBackTest(_Base):
    """驗收 1 前半：breakdown 資料覆蓋寫回對回的主題元件。"""

    def test_breakdown_maps_back_to_the_matching_component(self):
        theme = self._make_theme(components=[
            {"component_type": "body", "content": "虛構文案：晨光第一杯"},
            {"component_type": "title", "content": "虛構標題：晨光"},
        ])
        body_id = next(c["id"] for c in theme["components"] if c["component_type"] == "body")
        ad_id = self._map_ad(theme["campaign_cycle_id"])

        result = self._sync(component_breakdowns=[_breakdown(
            ad_id, body={"id": "asset_1", "text": "虛構文案：晨光第一杯"})])
        self.assertIsNone(result.error)

        row = main.conn.execute(
            "SELECT * FROM creative_theme_component WHERE id = %s", (body_id,)
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["meta_asset_id"], "asset_1")
        self.assertEqual(row["performance_impressions"], 1000)
        self.assertEqual(row["performance_clicks"], 50)
        self.assertEqual(row["performance_conversions"], 2)
        self.assertIsNotNone(row["performance_synced_at"])

        # 沒對回的 title 元件維持沒同步過的狀態
        title_id = next(c["id"] for c in theme["components"] if c["component_type"] == "title")
        title_row = main.conn.execute(
            "SELECT performance_synced_at FROM creative_theme_component WHERE id = %s",
            (title_id,)).fetchone()
        self.assertIsNone(title_row["performance_synced_at"])

    def test_second_sync_overwrites_instead_of_accumulating(self):
        """精簡版核心行為：覆蓋舊值，不像快照表那樣累積多筆。"""
        theme = self._make_theme(components=[
            {"component_type": "body", "content": "虛構文案：晨光第一杯"},
        ])
        body_id = theme["components"][0]["id"]
        ad_id = self._map_ad(theme["campaign_cycle_id"])

        self._sync(component_breakdowns=[_breakdown(
            ad_id, body={"id": "asset_1", "text": "虛構文案：晨光第一杯"},
            impressions=1000, clicks=50, conversions=2.0)])
        self._sync(component_breakdowns=[_breakdown(
            ad_id, body={"id": "asset_1", "text": "虛構文案：晨光第一杯"},
            impressions=3000, clicks=90, conversions=7.0)])

        row = main.conn.execute(
            "SELECT performance_impressions, performance_clicks, performance_conversions"
            " FROM creative_theme_component WHERE id = %s", (body_id,)).fetchone()
        self.assertEqual(row["performance_impressions"], 3000)
        self.assertEqual(row["performance_clicks"], 90)
        self.assertEqual(row["performance_conversions"], 7)

    def test_no_cycle_mapping_skips_entirely(self):
        """這支廣告還沒認領到任何檔期時，元件層歸因整批跳過（沒有元件可比對）。"""
        theme = self._make_theme(components=[
            {"component_type": "body", "content": "不會被存的文案"},
        ])
        body_id = theme["components"][0]["id"]

        result = self._sync(component_breakdowns=[_breakdown(
            "ad_unmapped", body={"id": "asset_x", "text": "不會被存的文案"})])
        self.assertIsNone(result.error)
        row = main.conn.execute(
            "SELECT performance_synced_at FROM creative_theme_component WHERE id = %s",
            (body_id,)).fetchone()
        self.assertIsNone(row["performance_synced_at"])

    def test_record_component_breakdown_skips_when_cycle_id_is_none(self):
        """單元層級直接驗證 theme_attribution 自己的跳過分支（不透過 sync.py 的品牌解析）。"""
        theme = self._make_theme(components=[{"component_type": "body", "content": "x"}])
        theme_attribution.record_component_breakdown(
            main.conn, self.bid, None, _breakdown("ad1", body={"id": "a1", "text": "x"}),
            actor=ACTOR)
        row = main.conn.execute(
            "SELECT performance_synced_at FROM creative_theme_component WHERE id = %s",
            (theme["components"][0]["id"],)).fetchone()
        self.assertIsNone(row["performance_synced_at"])

    def test_unresolvable_breakdown_does_not_raise(self):
        """有檔期歸屬，但文字對不回任何已存元件（bootstrap 找不到）：這一筆這次同步直接
        跳過，不報錯。"""
        theme = self._make_theme(components=[{"component_type": "body", "content": "文案A"}])
        ad_id = self._map_ad(theme["campaign_cycle_id"])
        result = self._sync(component_breakdowns=[_breakdown(
            ad_id, body={"id": "asset_x", "text": "查無此文案"})])
        self.assertIsNone(result.error)

    def test_breakdown_fetch_failure_does_not_break_ad_level_sync(self):
        """元件層歸因是加分項：這條路掛了不能拖累廣告層同步本身。"""
        class _FailingClient(meta_api.FakeMetaClient):
            def list_component_breakdowns(self, account_id, since, until):
                raise meta_api.MetaApiError("模擬元件層 breakdown 請求失敗")

        theme = self._make_theme(components=[{"component_type": "body", "content": "文案A"}])
        body_id = theme["components"][0]["id"]
        ad_id = self._map_ad(theme["campaign_cycle_id"])

        campaign = meta_api.Campaign(campaign_id="c1", name="不重要", objective="OUTCOME_SALES",
                                     effective_status="ACTIVE")
        insight = meta_api.Insight(campaign_id="c1", adset_id="as1", ad_id=ad_id,
                                   date_start="2026-08-01", date_stop="2026-08-07",
                                   impressions=100, clicks=5, spend=10.0, conversions=1.0,
                                   revenue=50.0)
        client = _FailingClient(campaigns=[campaign], insights=[insight])
        result = ads_sync.sync_account(main.conn, ACTOR, client=client, today="2026-08-31")

        self.assertIsNone(result.error)
        self.assertEqual(result.snapshots, 1)  # 廣告層照樣進來
        row = main.conn.execute(
            "SELECT performance_synced_at FROM creative_theme_component WHERE id = %s",
            (body_id,)).fetchone()
        self.assertIsNone(row["performance_synced_at"])


class MismatchReconciliationTest(_Base):
    """驗收 2、3：文字不一致 → 重打指紋＋更新存檔＋稽核；一致 → 零動作；指紋走引擎入口。"""

    def _setup_matched(self):
        theme = self._make_theme(components=[
            {"component_type": "body", "content": "虛構文案：原始版本"},
        ])
        body_id = theme["components"][0]["id"]
        ad_id = self._map_ad(theme["campaign_cycle_id"])
        self._sync(component_breakdowns=[_breakdown(
            ad_id, body={"id": "asset_1", "text": "虛構文案：原始版本"})])
        return theme, body_id, ad_id

    def test_consistent_text_is_zero_action(self):
        theme, body_id, ad_id = self._setup_matched()
        before_audit = main.conn.execute(
            "SELECT COUNT(*) c FROM audit_log WHERE entity_id = %s AND action = 'sync_from_meta'",
            (body_id,)).fetchone()["c"]

        self._sync(component_breakdowns=[_breakdown(
            ad_id, body={"id": "asset_1", "text": "虛構文案：原始版本"})])

        after_audit = main.conn.execute(
            "SELECT COUNT(*) c FROM audit_log WHERE entity_id = %s AND action = 'sync_from_meta'",
            (body_id,)).fetchone()["c"]
        self.assertEqual(before_audit, 0)
        self.assertEqual(after_audit, 0)
        component = theme_repo.get_component(main.conn, self.bid, body_id)
        self.assertEqual(component["content"], "虛構文案：原始版本")

    def test_changed_text_refreshes_fingerprint_updates_content_and_leaves_audit(self):
        theme, body_id, ad_id = self._setup_matched()
        self._swap_provider({"fingerprint": {"angle": "benefit", "tone": "warm",
                                             "format": "single_image", "selling_point": "quality"}})

        self._sync(component_breakdowns=[_breakdown(
            ad_id, body={"id": "asset_1", "text": "虛構文案：被人工改過的版本"})])

        component = theme_repo.get_component(main.conn, self.bid, body_id)
        self.assertEqual(component["content"], "虛構文案：被人工改過的版本")
        self.assertEqual(component["fingerprint_json"],
                         {"angle": "benefit", "tone": "warm", "format": "single_image",
                          "selling_point": "quality"})

        audit_row = main.conn.execute(
            "SELECT * FROM audit_log WHERE entity_id = %s AND action = 'sync_from_meta'",
            (body_id,)).fetchone()
        self.assertIsNotNone(audit_row)
        self.assertEqual(audit_row["actor"], ACTOR)

    def test_refresh_component_fingerprint_is_stateless_text_in_fingerprint_out(self):
        """驗收 3：引擎入口本身不碰主題／元件資料表，只吃文字回指紋。"""
        self._swap_provider({"fingerprint": {"angle": "proof", "tone": "professional",
                                             "format": "carousel", "selling_point": "price"}})
        result = theme_engine.refresh_component_fingerprint(main.conn, self.bid, "隨便一段文字")
        self.assertEqual(result, {"angle": "proof", "tone": "professional",
                                  "format": "carousel", "selling_point": "price"})

    def test_refresh_component_fingerprint_returns_none_on_ai_failure(self):
        from app.llm.providers import ProviderError

        theme_engine.PROVIDER = FakeProvider(exception=ProviderError("模擬 AI 失敗"))
        result = theme_engine.refresh_component_fingerprint(main.conn, self.bid, "文字")
        self.assertIsNone(result)


class ComponentRankingTest(_Base):
    """驗收 4：元件成效端點回相對排名所需資料，不提供絕對值對帳介面。"""

    def _seed_performance(self, component_id, *, conversions, impressions=100, clicks=10):
        main.conn.execute(
            "UPDATE creative_theme_component SET meta_asset_id = %s, performance_impressions = %s,"
            " performance_clicks = %s, performance_conversions = %s, performance_synced_at = %s"
            " WHERE id = %s",
            (new_id("asset"), impressions, clicks, conversions, now_iso(), component_id),
        )
        main.conn.commit()

    def test_ranks_within_each_component_type_by_conversions_and_excludes_absolute_money_fields(self):
        theme = self._make_theme(components=[
            {"component_type": "body", "content": "文案A"},
            {"component_type": "body", "content": "文案B"},
            {"component_type": "title", "content": "標題A"},
            {"component_type": "body", "content": "文案C：從沒同步過"},
        ])
        by_content = {c["content"]: c["id"] for c in theme["components"]}
        self._seed_performance(by_content["文案A"], conversions=2.0)
        self._seed_performance(by_content["文案B"], conversions=9.0)
        self._seed_performance(by_content["標題A"], conversions=1.0)
        # 文案C 沒被 _seed_performance 過（performance_synced_at 是 NULL），不該出現在排名裡

        ranking = theme_attribution.rank_theme_components(main.conn, self.bid, theme["id"])
        self.assertEqual(len(ranking), 3)
        for item in ranking:
            self.assertNotIn("spend", item)
            self.assertNotIn("revenue", item)

        by_id = {item["component_id"]: item for item in ranking}
        self.assertEqual(by_id[by_content["文案B"]]["rank"], 1)
        self.assertEqual(by_id[by_content["文案A"]]["rank"], 2)
        self.assertEqual(by_id[by_content["標題A"]]["rank"], 1)  # 不同型別各自排名

    def test_performance_endpoint_returns_ranking(self):
        theme = self._make_theme(components=[{"component_type": "body", "content": "文案A"}])
        component_id = theme["components"][0]["id"]
        self._seed_performance(component_id, conversions=3.0)

        resp = self.client.get(
            f"/api/ads/brands/{self.bid}/ads/{theme['campaign_cycle_id']}"
            f"/themes/{theme['id']}/components/performance")
        self.assertEqual(resp.status_code, 200)
        components = resp.json()["components"]
        self.assertEqual(len(components), 1)
        self.assertEqual(components[0]["component_id"], component_id)
        self.assertEqual(components[0]["rank"], 1)
        self.assertNotIn("spend", components[0])


if __name__ == "__main__":
    unittest.main()
