# -*- coding: utf-8 -*-
"""app/tests/test_preselect_batch.py — 預選格批次生成（票 09-preselect-autogen）。

接縫二（路由層，app/ads/routes_plan.py `plan/approve`）：核准計畫觸發批次生成，走真正的
HTTP POST，驗每格恰 2 主題、非預選格式零生成（驗收 1）。接縫一（批次函式門口，
app/ads/theme_batch.py `generate_preselected_batch`）：同格第二主題的簡報真的帶上第一個的
摘要、指紋距離夠遠不標黃，故意讓兩個主題撞指紋則反過來標黃證明檢查真的有作用（驗收 2）；
費用攔截對批次生效、超上限誠實停下、已生成的保留（驗收 4）。矩陣端點三態 JSON（驗收 3）。

全程 FakeProvider／_SequencedProvider，不發任何真實網路請求。品牌與產品名一律虛構。
setUp／_ready_cell 等寫法照抄 app/tests/test_theme_engine.py、test_video_theme.py（票
04／08）——本專案測試檔一律自帶獨立 tmp DB，不共用 import。
"""

import atexit
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_preselect_batch_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.ads import theme_batch  # noqa: E402
from app.ads import theme_engine  # noqa: E402
from app.ads import theme_repository as theme_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import creative_assets  # noqa: E402
from app.core import db  # noqa: E402
from app.core import settings as coresettings  # noqa: E402
from app.llm import pricing, providers  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402


ROOT = Path(_tmpdir) / "creative"


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"
_BASE_FP = {"angle": "benefit", "tone": "warm", "format": "single_image", "selling_point": "quality"}
_FAR_FP = {"angle": "pain", "tone": "urgent", "format": "carousel", "selling_point": "price"}

# 兩組各 5 個「家族內互不相似、跨家族一定相似度夠遠」的指紋——用來測「第二主題跟第一主題
# 距離夠遠」時排除掉「同一主題內 5 則文案彼此撞了」這個雜訊。兩組四軸完全不重疊
# 選值（angle／tone／format／selling_point 各自取兩個沒交集的字），所以跨組任兩則的
# distance 恆為 1.0；組內 5 則兩兩至少 2 軸不同（distance ≥ 0.5），不會被 threshold
# 0.25 標黃。
_FAMILY_A = [
    {"angle": "benefit", "tone": "warm", "format": "single_image", "selling_point": "quality"},
    {"angle": "pain", "tone": "professional", "format": "single_image", "selling_point": "quality"},
    {"angle": "benefit", "tone": "warm", "format": "carousel", "selling_point": "price"},
    {"angle": "pain", "tone": "warm", "format": "carousel", "selling_point": "quality"},
    {"angle": "benefit", "tone": "professional", "format": "single_image", "selling_point": "price"},
]
_FAMILY_B = [
    {"angle": "proof", "tone": "humorous", "format": "short_video", "selling_point": "efficacy"},
    {"angle": "testimonial", "tone": "urgent", "format": "short_video", "selling_point": "efficacy"},
    {"angle": "proof", "tone": "humorous", "format": "text_focus", "selling_point": "convenience"},
    {"angle": "testimonial", "tone": "humorous", "format": "text_focus", "selling_point": "efficacy"},
    {"angle": "proof", "tone": "urgent", "format": "short_video", "selling_point": "convenience"},
]


def _fake(text: str) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=400, output_tokens=250),
                            stop_reason="end_turn")


def _theme_reply(*, name: str, body_fps) -> str:
    """body_fps：單一 dict（5 則文案全用同一組指紋，會互相撞——用於「本來就該標黃」的
    測試）或 5 個 dict 組成的 list（各則指紋不同，用於「不該互相干擾」的測試）。title／
    description 故意不附指紋（fp.normalize(None) 收斂成空字典，_apply_similarity_flag
    看到空字典就跳過）——這裡只要測 body 元件的相似度查核，不必連 title／description
    也各自造一組互不相似的指紋。"""
    if isinstance(body_fps, dict):
        body_fps = [body_fps] * 5
    payload = {
        "name": name,
        "image_prompt": [f"暖金色茶席場景，特寫第 {i} 張" for i in range(10)],
        "body": [{"content": f"文案{i}", "fingerprint": fp} for i, fp in enumerate(body_fps)],
        "title": [{"content": f"標題{i}"} for i in range(5)],
        "description": [{"content": f"說明{i}"} for i in range(5)],
    }
    return json.dumps(payload, ensure_ascii=False)


class _SequencedProvider:
    """依序回傳不同回覆的假 Provider（照抄 app/tests/test_video_theme.py 同名類別）：
    第一次呼叫給第一個主題的內容，第二次以後給第二個主題的內容。"""

    name = "fake-sequenced"

    def __init__(self, replies: list):
        self._responses = [_fake(text) for text in replies]
        self.calls: list = []

    def complete(self, *, model, system, messages, max_tokens, timeout_s=120.0, effort=None):
        self.calls.append({"model": model, "system": system, "messages": messages,
                           "max_tokens": max_tokens, "timeout_s": timeout_s})
        index = min(len(self.calls) - 1, len(self._responses) - 1)
        return self._responses[index]


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        coresettings.set_setting(main.conn, creative_assets.SETTING_KEY, str(ROOT))
        coresettings.set_setting(main.conn, "intake_budget_limit", "1000")
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡（預選批次票）",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        self.product_id = bi_repo.create_product(main.conn, self.bid, name="虛構濾掛組",
                                                  actor=ACTOR)["id"]
        self._orig_provider = theme_engine.PROVIDER

    def tearDown(self):
        theme_engine.PROVIDER = self._orig_provider
        coresettings.set_setting(main.conn, "intake_budget_limit", "1000")

    def _open_cycle(self, *, objective: str = "sales") -> str:
        cycle = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[self.product_id],
            pain_value=5, objective=objective, actor=ACTOR,
        )
        return cycle["id"]

    def _insert_cell(self, cycle_id: str, *, angle: str = "價格敏感：第一杯 39 元") -> str:
        cell_id = db.new_id("exc")
        main.conn.execute(
            "INSERT INTO experiment_cell (id, campaign_cycle_id, brand_id, product_id,"
            " creative_angle, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (cell_id, cycle_id, self.bid, self.product_id, angle, db.now_iso()),
        )
        main.conn.commit()
        return cell_id

    def _insert_draft_plan(self, cycle_id: str) -> None:
        main.conn.execute(
            "INSERT INTO campaign_plan (id, campaign_cycle_id, brand_id, plan_version,"
            " plan_json, status, approved_by, approved_at, created_at)"
            " VALUES (?, ?, ?, ?, ?, 'draft', NULL, NULL, ?)",
            (db.new_id("cpl"), cycle_id, self.bid, 1,
             json.dumps({"summary": "測試打法：主打省錢誘因"}, ensure_ascii=False),
             db.now_iso()),
        )
        main.conn.commit()

    def _insert_approved_plan(self, cycle_id: str) -> None:
        main.conn.execute(
            "INSERT INTO campaign_plan (id, campaign_cycle_id, brand_id, plan_version,"
            " plan_json, status, approved_by, approved_at, created_at)"
            " VALUES (?, ?, ?, ?, ?, 'approved', ?, ?, ?)",
            (db.new_id("cpl"), cycle_id, self.bid, 1,
             json.dumps({"summary": "測試打法：主打省錢誘因"}, ensure_ascii=False),
             ACTOR, db.now_iso(), db.now_iso()),
        )
        main.conn.commit()

    def _swap_sequenced(self, replies: list) -> _SequencedProvider:
        provider = _SequencedProvider(replies)
        theme_engine.PROVIDER = provider
        return provider

    def _insert_historical_performance(self, cycle_id: str, *, angle: str,
                                       spend: float, conversions: float) -> str:
        cell_id = self._insert_cell(cycle_id, angle=angle)
        package_id = db.new_id("pkg")
        mapping_id = db.new_id("xam")
        ts = db.now_iso()
        main.conn.execute(
            "INSERT INTO publishing_package (id, brand_id, campaign_cycle_id,"
            " experiment_cell_id, campaign_name, adset_name, ad_name, destination_url,"
            " utm_json, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', 'ready', ?)",
            (package_id, self.bid, cycle_id, cell_id, "虛構歷史活動", "虛構歷史組合",
             f"虛構歷史廣告：{angle}", "https://example.test", ts),
        )
        main.conn.execute(
            "INSERT INTO external_ad_mapping (id, brand_id, publishing_package_id,"
            " campaign_cycle_id, platform, claim_status, confirmed_by, confirmed_at, created_at)"
            " VALUES (?, ?, ?, ?, 'meta', 'confirmed', ?, ?, ?)",
            (mapping_id, self.bid, package_id, cycle_id, ACTOR, ts, ts),
        )
        main.conn.execute(
            "INSERT INTO performance_snapshot (id, brand_id, campaign_cycle_id,"
            " external_ad_mapping_id, platform, date_range_start, date_range_end, as_of_date,"
            " snapshot_taken_at, currency, spend, conversions, raw_json, source, created_at)"
            " VALUES (?, ?, ?, ?, 'meta', '2026-01-01', '2026-01-07', '2026-01-07', ?,"
            " 'TWD', ?, ?, '{}', 'manual', ?)",
            (db.new_id("psn"), self.bid, cycle_id, mapping_id, ts, spend, conversions, ts),
        )
        main.conn.commit()
        return cell_id

    def _set_cycle_created_at(self, cycle_id: str, created_at: str) -> None:
        main.conn.execute(
            "UPDATE campaign_cycle SET created_at = ?, updated_at = ? WHERE id = ?",
            (created_at, created_at, cycle_id),
        )
        main.conn.commit()

    def _insert_adopted_fingerprint(self, cycle_id: str, fingerprint: dict) -> None:
        main.conn.execute(
            "INSERT INTO adoption_decision (id, brand_id, campaign_cycle_id, target_type,"
            " target_id, decision, fingerprint_json, decided_by, decided_at)"
            " VALUES (?, ?, ?, 'variant', ?, 'adopted', ?, ?, ?)",
            (db.new_id("adp"), self.bid, cycle_id, db.new_id("cvr"),
             json.dumps(fingerprint, ensure_ascii=False), ACTOR, db.now_iso()),
        )
        main.conn.commit()

    def _insert_variant_fingerprint(self, cycle_id: str, fingerprint: dict) -> None:
        """票 02-repoint-creative-readers：素材讀取源已改主題表，`check_echo_chamber()`
        經 `creative.list_variants()` 讀，只認已採用主題（D4）——這裡改直接建一顆已採用
        主題（含一個文案元件），不再插 creative_variant，那張表已經沒有任何讀取路徑會看。"""
        cell_id = self._insert_cell(cycle_id, angle="虛構切角：前一期")
        theme_repo.create_theme(
            main.conn, self.bid, campaign_cycle_id=cycle_id, experiment_cell_id=cell_id,
            format_key=fingerprint.get("format", "single_image"), name="虛構回音室測試主題",
            folder_code="ECH0", actor=ACTOR, status="adopted",
            components=[{"component_type": "body", "content": "虛構回音室測試",
                        "fingerprint_json": fingerprint}],
        )


class ApproveTriggersBatchTest(_Base):
    """票 09 驗收 1：核准計畫觸發預選格批次生成，每格恰 2 主題；非預選格零生成。"""

    def test_approve_route_generates_exactly_two_single_image_themes_per_cell(self):
        cycle_id = self._open_cycle(objective="sales")
        cell_id = self._insert_cell(cycle_id)
        self._insert_draft_plan(cycle_id)
        self._swap_sequenced([
            _theme_reply(name="虛構主題：暖金茶席", body_fps=_BASE_FP),
            _theme_reply(name="虛構主題：墨青茶席", body_fps=_FAR_FP),
        ])

        resp = self.client.post(f"/api/campaigns/{self.bid}/{cycle_id}/plan/approve")
        self.assertEqual(resp.status_code, 204)

        themes = theme_repo.list_themes_for_cell(main.conn, self.bid, cell_id)
        by_format: dict = {}
        for t in themes:
            by_format.setdefault(t["format_key"], []).append(t)
        self.assertEqual(len(by_format.get("single_image", [])), 2)
        self.assertEqual(by_format.get("carousel", []), [])
        self.assertEqual(by_format.get("video", []), [])

    def test_multiple_cells_each_get_their_own_pair(self):
        cycle_id = self._open_cycle(objective="sales")
        cell_a = self._insert_cell(cycle_id, angle="價格敏感：第一杯 39 元")
        cell_b = self._insert_cell(cycle_id, angle="便利：辦公室手沖")
        self._insert_draft_plan(cycle_id)
        self._swap_sequenced([
            _theme_reply(name="A1", body_fps=_BASE_FP), _theme_reply(name="A2", body_fps=_FAR_FP),
            _theme_reply(name="B1", body_fps=_BASE_FP), _theme_reply(name="B2", body_fps=_FAR_FP),
        ])

        resp = self.client.post(f"/api/campaigns/{self.bid}/{cycle_id}/plan/approve")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(len(theme_repo.list_themes_for_cell(main.conn, self.bid, cell_a)), 2)
        self.assertEqual(len(theme_repo.list_themes_for_cell(main.conn, self.bid, cell_b)), 2)


class HistoricalQuotaFeedbackTest(_Base):
    """P1：真正帶單／明確沒帶單／還不知道三型切角，直接改變同一個批次迴圈的生成數。"""

    def test_trusted_conversion_gains_one_underperformer_loses_one_and_unknown_stays_neutral(self):
        history_cycle = self._open_cycle(objective="sales")
        main.conn.execute("UPDATE campaign_cycle SET budget = 3000 WHERE id = ?", (history_cycle,))
        self._insert_historical_performance(
            history_cycle, angle="虛構切角：可信帶單", spend=700, conversions=50)
        self._insert_historical_performance(
            history_cycle, angle="虛構切角：花過半沒帶單", spend=600, conversions=0)
        self._insert_historical_performance(
            history_cycle, angle="虛構切角：樣本還不足", spend=300, conversions=20)

        cycle_id = self._open_cycle(objective="sales")
        converting = self._insert_cell(cycle_id, angle="虛構切角：可信帶單")
        underperforming = self._insert_cell(cycle_id, angle="虛構切角：花過半沒帶單")
        unknown = self._insert_cell(cycle_id, angle="虛構切角：樣本還不足")
        self._insert_approved_plan(cycle_id)
        self._swap_sequenced([
            _theme_reply(name=f"虛構回流主題 {index}", body_fps=_FAMILY_A)
            for index in range(6)
        ])

        result = theme_batch.generate_preselected_batch(
            main.conn, self.bid, cycle_id, actor=ACTOR)

        self.assertEqual(result["errors"], [])
        self.assertEqual(len(theme_repo.list_themes_for_cell(main.conn, self.bid, converting)), 3)
        self.assertEqual(len(theme_repo.list_themes_for_cell(main.conn, self.bid, underperforming)), 1)
        self.assertEqual(len(theme_repo.list_themes_for_cell(main.conn, self.bid, unknown)), 2)


class EchoChamberReservationTest(_Base):
    """P1：只有最近一期真的亮回音室燈，批次才保留一組遠距指紋方向。"""

    def _ready_three_cycles(self, previous_fingerprint: dict) -> tuple:
        history_cycle = self._open_cycle(objective="sales")
        self._set_cycle_created_at(history_cycle, "2026-01-01T00:00:00")
        self._insert_adopted_fingerprint(history_cycle, _BASE_FP)

        previous_cycle = self._open_cycle(objective="sales")
        self._set_cycle_created_at(previous_cycle, "2026-01-02T00:00:00")
        self._insert_variant_fingerprint(previous_cycle, previous_fingerprint)

        cycle_id = self._open_cycle(objective="sales")
        self._set_cycle_created_at(cycle_id, "2026-01-03T00:00:00")
        self._insert_cell(cycle_id, angle="虛構切角：本期新方向")
        self._insert_approved_plan(cycle_id)
        provider = self._swap_sequenced([
            _theme_reply(name="虛構遠距主題", body_fps=_FAMILY_B),
            _theme_reply(name="虛構一般主題", body_fps=_FAMILY_A),
        ])
        return cycle_id, provider

    def test_lit_previous_cycle_reserves_exactly_one_group_with_farthest_same_format_target(self):
        cycle_id, provider = self._ready_three_cycles(_BASE_FP)

        result = theme_batch.generate_preselected_batch(
            main.conn, self.bid, cycle_id, actor=ACTOR)

        self.assertEqual(result["errors"], [])
        prompts = [call["messages"][0]["content"] for call in provider.calls]
        marker = "這組刻意改用"
        self.assertEqual(sum(marker in prompt for prompt in prompts), 1)
        # single_image 格式固定不變；其餘三軸挑到與既有指紋距離 0.75 的最遠組合。
        self.assertIn("點出痛點・專業可靠・單張圖・有感有效", prompts[0])
        self.assertIn("直說好處・親切溫暖・單張圖・品質好", prompts[0])

    def test_unlit_previous_cycle_keeps_prompts_unchanged(self):
        cycle_id, provider = self._ready_three_cycles(_FAR_FP)

        result = theme_batch.generate_preselected_batch(
            main.conn, self.bid, cycle_id, actor=ACTOR)

        self.assertEqual(result["errors"], [])
        prompts = [call["messages"][0]["content"] for call in provider.calls]
        self.assertFalse(any("這組刻意改用" in prompt for prompt in prompts))
        self.assertNotIn("這一格已經有以下主題", prompts[0])
        self.assertNotIn("直說好處・親切溫暖・單張圖・品質好", prompts[0])


class AntiDuplicateChainTest(_Base):
    """票 09 驗收 2：同格第二主題與第一主題指紋距離夠遠——驗整條鏈路（批次重新組簡報 →
    第二個主題的 prompt 真的帶上第一個的摘要 → 存檔前的相似度查核真的用得到這份摘要）。"""

    def test_second_theme_brief_carries_first_themes_summary_and_stays_unflagged_when_far(self):
        cycle_id = self._open_cycle(objective="sales")
        cell_id = self._insert_cell(cycle_id)
        self._insert_approved_plan(cycle_id)
        provider = self._swap_sequenced([
            _theme_reply(name="虛構主題：暖金茶席", body_fps=_FAMILY_A),
            _theme_reply(name="虛構主題：墨青茶席", body_fps=_FAMILY_B),
        ])

        result = theme_batch.generate_preselected_batch(
            main.conn, self.bid, cycle_id, actor=ACTOR)
        self.assertEqual(result["errors"], [])
        self.assertFalse(result["budget_stopped"])
        self.assertEqual(len(result["themes"]), 2)

        # 第二次呼叫（provider.calls[1]）的 prompt 裡要看得到第一個主題的名稱與防撞衫指令，
        # 證明批次重新組簡報時真的查到了剛存的第一個主題（brief_assembler →
        # theme_repository.list_themes_for_cell，不是本票新寫的邏輯，這裡驗的是「有接上」）。
        second_prompt = provider.calls[1]["messages"][0]["content"]
        self.assertIn("虛構主題：暖金茶席", second_prompt)
        self.assertIn("不要撞衫", second_prompt)

        # 指紋差很遠（4 軸全不同）→ 第二個主題的文案元件不標相似度黃旗標。
        second_theme = result["themes"][1]
        body_components = [c for c in second_theme["components"] if c["component_type"] == "body"]
        self.assertEqual(len(body_components), 5)
        self.assertFalse(any(c["similarity_flag"] for c in body_components))

    def test_red_proof_identical_fingerprints_do_get_flagged(self):
        """證明上面那條「不標黃」的斷言不是因為檢查本身沒在跑：故意讓兩個主題撞同一組指紋，
        第二個主題的文案元件必須全部標黃——這是 code-rules 要求的「新增檢查要證明會紅」。"""
        cycle_id = self._open_cycle(objective="sales")
        self._insert_cell(cycle_id)
        self._insert_approved_plan(cycle_id)
        self._swap_sequenced([
            _theme_reply(name="虛構主題：暖金茶席", body_fps=_BASE_FP),
            _theme_reply(name="虛構主題：撞衫版", body_fps=_BASE_FP),  # 故意跟第一個一樣
        ])

        result = theme_batch.generate_preselected_batch(
            main.conn, self.bid, cycle_id, actor=ACTOR)
        self.assertEqual(len(result["themes"]), 2)
        second_theme = result["themes"][1]
        body_components = [c for c in second_theme["components"] if c["component_type"] == "body"]
        self.assertTrue(all(c["similarity_flag"] for c in body_components))


class MatrixEndpointTest(_Base):
    """票 09 驗收 3：矩陣端點回 JSON，每格狀態足以渲染畫面契約的三態格。"""

    def test_full_grid_expansion_with_themed_and_empty_states(self):
        cycle_id = self._open_cycle(objective="sales")
        cell_id = self._insert_cell(cycle_id)
        self._insert_approved_plan(cycle_id)
        self._swap_sequenced([
            _theme_reply(name="虛構主題：暖金茶席", body_fps=_BASE_FP),
            _theme_reply(name="虛構主題：墨青茶席", body_fps=_FAR_FP),
        ])
        theme_batch.generate_preselected_batch(main.conn, self.bid, cycle_id, actor=ACTOR)

        resp = self.client.get(f"/api/ads/brands/{self.bid}/ads/{cycle_id}/matrix")
        self.assertEqual(resp.status_code, 200)
        cells = resp.json()["cells"]
        self.assertEqual(len(cells), 1)
        row = cells[0]
        self.assertEqual(row["experiment_cell_id"], cell_id)
        # 全展開：即使 carousel／video 從沒生成過，欄位仍然存在，不是整欄消失。
        self.assertEqual(set(row["formats"].keys()), {"single_image", "carousel", "video"})

        single_image = row["formats"]["single_image"]
        self.assertEqual(single_image["state"], "themed")
        self.assertEqual(len(single_image["themes"]), 2)
        self.assertEqual({t["name"] for t in single_image["themes"]},
                         {"虛構主題：暖金茶席", "虛構主題：墨青茶席"})

        for empty_format in ("carousel", "video"):
            cell_state = row["formats"][empty_format]
            self.assertEqual(cell_state["state"], "empty")
            self.assertGreater(cell_state["estimated_cost"], 0)

    def test_cell_with_no_themes_at_all_is_all_empty(self):
        cycle_id = self._open_cycle(objective="sales")
        self._insert_cell(cycle_id)
        self._insert_approved_plan(cycle_id)

        resp = self.client.get(f"/api/ads/brands/{self.bid}/ads/{cycle_id}/matrix")
        self.assertEqual(resp.status_code, 200)
        row = resp.json()["cells"][0]
        self.assertTrue(all(f["state"] == "empty" for f in row["formats"].values()))


class BudgetCeilingBatchTest(_Base):
    """票 09 驗收 4：費用攔截對批次生效——超上限時整批誠實停下，已生成的保留。"""

    def test_zero_budget_stops_before_any_call(self):
        cycle_id = self._open_cycle(objective="sales")
        cell_id = self._insert_cell(cycle_id)
        self._insert_approved_plan(cycle_id)
        coresettings.set_setting(main.conn, "intake_budget_limit", "0.0001")
        provider = self._swap_sequenced([_theme_reply(name="不該被用到", body_fps=_BASE_FP)])

        result = theme_batch.generate_preselected_batch(
            main.conn, self.bid, cycle_id, actor=ACTOR)
        self.assertTrue(result["budget_stopped"])
        self.assertEqual(result["themes"], [])
        self.assertEqual(provider.calls, [])  # 真的沒花到錢
        self.assertEqual(theme_repo.list_themes_for_cell(main.conn, self.bid, cell_id), [])

    def test_budget_that_covers_exactly_one_theme_keeps_the_first_and_stops_honestly(self):
        cycle_id = self._open_cycle(objective="sales")
        cell_id = self._insert_cell(cycle_id)
        self._insert_approved_plan(cycle_id)

        model = providers.resolve_model(task_type="creative_theme", conn=main.conn)
        ceiling = pricing.cost_ceiling(model, theme_engine.THEME_MAX_TOKENS)
        # 剛好卡在「第一次呼叫前檢查會過、第一次呼叫真的花掉一點錢之後，第二次呼叫前檢查
        # 就會超」的邊界——算法跟 app/ads/theme_batch.py._budget_blocked 用同一組函式，
        # 不是憑感覺挑一個數字。
        coresettings.set_setting(main.conn, "intake_budget_limit", str(ceiling))
        self._swap_sequenced([
            _theme_reply(name="虛構主題：暖金茶席", body_fps=_BASE_FP),
            _theme_reply(name="不該被用到", body_fps=_FAR_FP),
        ])

        result = theme_batch.generate_preselected_batch(
            main.conn, self.bid, cycle_id, actor=ACTOR)
        self.assertTrue(result["budget_stopped"])
        self.assertEqual(len(result["themes"]), 1)  # 已生成的保留，不回滾
        self.assertEqual(result["themes"][0]["name"], "虛構主題：暖金茶席")
        stored = theme_repo.list_themes_for_cell(main.conn, self.bid, cell_id)
        self.assertEqual(len(stored), 1)


if __name__ == "__main__":
    unittest.main()
