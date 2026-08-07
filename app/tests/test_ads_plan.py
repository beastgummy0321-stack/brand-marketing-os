# -*- coding: utf-8 -*-
"""app/tests/test_ads_plan.py — 廣告分支票 4：計畫多方案生成、受眾三層、選定＋第一道人工關卡。

全程 FakeProvider，不發任何真實網路請求；品牌與產品名一律虛構。

流程改成兩步（決策 0023 第 1 點）：
  1. `plan/progress?run=1` 一次生成 2–4 個方案，存進暫存表，檔期狀態轉 PLAN_SELECT。
  2. `plan/select`（POST）老闆選定一個，才落地成正式計畫（沿用既有版本機制），
     檔期狀態轉 REVIEW，接著走既有關卡一 `plan/approve`（行為不變）。
"""

import atexit
import json
import os
import re
import shutil
import tempfile
import time
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_plan_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import plan as ads_plan  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import settings as coresettings  # noqa: E402
from app.core.db import new_id, now_iso  # noqa: E402
from app.llm import methodology  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402
from app.shared.web import OPERATOR  # noqa: E402

main.reopen_connection()


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"

_GOOD_OPTIONS = {
    "options": [
        {
            "is_recommended": True,
            "summary": "先用早晨儀式感的說法打通勤族，測三種切角哪個帶得動下單。",
            "difference": "主打通勤族的省錢與快速訴求，冷受眾優先。",
            "audience": {
                "cold": {"description": "住雙北、每天通勤超過三十分鐘的上班族。"
                                        "習慣買超商咖啡，但嫌口味太淡。"},
                "warm": {"description": ""},
                "hot": {"description": ""},
                "exclusions": ["近 30 天已下單的老客戶"],
            },
            "angles": [
                {"title": "早上第一杯", "message": "三分鐘沖一杯比超商好喝的",
                 "why": "通勤族最在意的是快", "product_id": None},
                {"title": "比超商省一半", "message": "一天一杯，一個月省下的錢",
                 "why": "價格敏感族群的切入點", "product_id": None},
                {"title": "單一產區", "message": "喝得出來的產區風味", "why": "拉出品牌差異",
                 "product_id": None},
                {"title": "辦公室共享", "message": "一盒放茶水間，同事都說好",
                 "why": "帶出團購可能", "product_id": None},
            ],
            "hypotheses": [
                {"type": "audience", "statement": "通勤族比在家工作者更會下單",
                 "verify": "看兩組受眾的每筆訂單成本差多少"},
                {"type": "message", "statement": "講省錢比講風味有效",
                 "verify": "比兩個切角的點擊率"},
            ],
            "grounding": {
                "facts": ["品牌主打單一產區", "產品是濾掛式"],
                "inferences": ["通勤族可能是主要客群"],
                "to_verify": ["省錢訴求是否比風味訴求有效"],
            },
        },
        {
            "is_recommended": False,
            "summary": "改用風味鑑賞角度打咖啡愛好者，測精品定位能不能撐住價格。",
            "difference": "不打通勤族，改打願意為風味付費的鑑賞型客群。",
            "audience": {
                "cold": {"description": "對精品咖啡有興趣、關注產區與烘豆方式的族群。"},
                "warm": {"description": ""},
                "hot": {"description": ""},
                "exclusions": [],
            },
            "angles": [
                {"title": "產區故事", "message": "這一批豆子的產地與烘焙師",
                 "why": "鑑賞族群買故事", "product_id": None},
            ],
            "hypotheses": [],
            "grounding": {"facts": [], "inferences": [], "to_verify": []},
        },
    ]
}

# 只有一個方案的角度是空的 → 有效方案數 0，不足 MIN_OPTION_COUNT，整批算失敗
_INSUFFICIENT_OPTIONS = {
    "options": [
        {**_GOOD_OPTIONS["options"][0], "angles": []},
    ]
}

# 票 5：具名異議，三種 target 各給一筆
_DISSENT_ITEMS = [
    {"target": "account_structure", "suggestion": "這期先別分兩組，全部押單一測試組。",
     "reason": "背景寫著這是全新品牌，還沒有任何投放歷史，拆組只會兩組都學不起來。"},
    {"target": "budget_allocation", "suggestion": "驗證與測試各半，不要 70/30。",
     "reason": "這個品牌過去沒有任何贏家素材可言，沒有可驗證的方向。"},
    {"target": "offer", "suggestion": "建議至少加一個保證或限時加贈再開跑。",
     "reason": "目前掌握的資料只有商品與定價，沒有任何保證，容易被當成純廣告滑掉。"},
]


def _with_dissents(*items):
    return json.dumps({**_GOOD_OPTIONS, "dissents": list(items)}, ensure_ascii=False)


def _fake(text: str) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=800, output_tokens=400),
                            stop_reason="end_turn")


def _wait_progress(client, url, params=None, timeout=5.0):
    """票 M3：進度頁改背景執行緒後，?run=1 不再同步等完；短輪詢模擬瀏覽器 meta refresh，
    等到真的轉址（303）或逾時為止（FakeProvider 幾乎瞬間完成，正常情況幾毫秒內就會轉址）。"""
    deadline = time.time() + timeout
    resp = client.get(url, params=params, follow_redirects=False)
    while resp.status_code != 303 and time.time() < deadline:
        time.sleep(0.02)
        resp = client.get(url, params=params, follow_redirects=False)
    return resp


def _seed_snapshot(brand_id: str, *, clicks: int = 0, conversions: int = 0) -> None:
    """造一筆成效快照，供受眾可用性測試用（暖層要 clicks、熱層要 conversions）。"""
    ts = now_iso()
    main.conn.execute(
        "INSERT INTO performance_snapshot (id, brand_id, platform, date_range_start,"
        " date_range_end, as_of_date, snapshot_taken_at, currency, clicks, conversions,"
        " quarantined, source, created_at) VALUES (?, ?, 'meta', '2026-01-01', '2026-01-07',"
        " '2026-01-07', ?, 'TWD', ?, ?, 0, 'manual', ?)",
        (new_id("psn"), brand_id, ts, clicks, conversions, ts),
    )
    main.conn.commit()


class _BasePlanTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        self.product = bi_repo.create_product(main.conn, self.bid, name="虛構濾掛組",
                                              actor=ACTOR)["id"]
        bi_repo.create_brand_fact(main.conn, self.bid, actor=ACTOR, fact_type="positioning",
                                  label="定位", value="單一產區濾掛咖啡。",
                                  status="confirmed", confirmed_by=ACTOR)
        resp = self.client.post(f"/brands/{self.bid}/ads/new",
                                data={"product_ids": [self.product], "slider_index": "5",
                                      "objective": "sales"}, follow_redirects=False)
        self.cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]
        self._orig_provider = ads_plan.PROVIDER

    def tearDown(self):
        ads_plan.PROVIDER = self._orig_provider

    def _generate(self, reply=None, direction=None):
        ads_plan.PROVIDER = FakeProvider(
            response=_fake(reply if reply is not None
                           else json.dumps(_GOOD_OPTIONS, ensure_ascii=False)))
        params = {"run": "1"}
        if direction:
            params["direction"] = direction
        return _wait_progress(
            self.client, f"/brands/{self.bid}/ads/{self.cycle_id}/plan/progress", params=params)

    def _select(self, option_id=None):
        data = {"option_id": option_id} if option_id else {}
        return self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/plan/select",
                                data=data, follow_redirects=False)

    def _generate_and_select(self, option_id=None):
        self._generate()
        return self._select(option_id)


class PlanGenerationTest(_BasePlanTest):
    def test_progress_page_before_running(self):
        resp = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/plan/progress")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("正在規劃這期的打法", resp.text)
        self.assertIn("run=1", resp.text)

    def test_progress_page_stage_list_is_honest_before_running(self):
        """票 29：真的什麼都還沒做的時候，不能有任何一階段標「完成」；也不能有百分比或
        假進度條——這是這張票要修的原本假狀態問題（比照 intake/routes.py 舊寫法的反例）。"""
        text = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/plan/progress").text
        for label in ("整理這期的資料與方法論", "請 AI 生成方案", "把方案存起來"):
            self.assertIn(label, text)
        self.assertIn("進行中", text)
        self.assertIn("還沒開始", text)
        self.assertNotIn("完成", text)
        self.assertNotIn("%", text)
        self.assertIn("已等", text)
        self.assertIn("通常範圍", text)

    def test_progress_elapsed_time_does_not_reset_on_reload(self):
        """已等秒數以後端記錄的流程開始時間計算，重刷（等同再打一次同一個等待頁）
        天然不會歸零。"""
        first = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/plan/progress").text
        first_secs = int(re.search(r"(\d+) 秒／通常範圍", first).group(1))
        time.sleep(1.1)
        second = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/plan/progress").text
        second_secs = int(re.search(r"(\d+) 秒／通常範圍", second).group(1))
        self.assertGreaterEqual(second_secs, first_secs + 1)

    def test_generate_options_reports_real_stages_in_order(self):
        """後端在長流程各階段更新目前階段狀態：呼叫 AI 前後各回報一次，且順序正確
        （不是憑空寫死的假狀態）。"""
        provider = FakeProvider(response=_fake(json.dumps(_GOOD_OPTIONS, ensure_ascii=False)))
        ads_plan.PROVIDER = provider
        seen = []
        ok, err = ads_plan.generate_options(main.conn, self.bid, self.cycle_id, ACTOR,
                                            on_stage=seen.append)
        self.assertTrue(ok, err)
        self.assertEqual(seen, ["ask_ai", "save"])

    def test_options_are_stored_and_cycle_waits_for_selection(self):
        resp = self._generate()
        self.assertEqual(resp.status_code, 303)
        self.assertIn("/plan/select", resp.headers["location"])
        cycle = ads_repo.get_cycle(main.conn, self.bid, self.cycle_id)
        self.assertEqual(cycle["status"], "PLAN_SELECT")
        self.assertIsNone(ads_plan.get_latest_plan(main.conn, self.bid, self.cycle_id))

        options = ads_plan.get_pending_options(main.conn, self.bid, self.cycle_id)
        self.assertEqual(len(options), 2)
        recommended = [o for o in options if o["is_recommended"]]
        self.assertEqual(len(recommended), 1)
        self.assertEqual(recommended[0]["summary"], _GOOD_OPTIONS["options"][0]["summary"])

    def test_selecting_recommended_option_persists_plan_and_moves_to_review(self):
        self._generate()
        resp = self._select()
        self.assertEqual(resp.status_code, 303)
        cycle = ads_repo.get_cycle(main.conn, self.bid, self.cycle_id)
        self.assertEqual(cycle["status"], "REVIEW")
        self.assertEqual(cycle["plan_version"], 1)
        stored = ads_plan.get_latest_plan(main.conn, self.bid, self.cycle_id)
        self.assertEqual(stored["status"], "draft")
        self.assertEqual(len(stored["plan"]["angles"]), 4)
        self.assertTrue(stored["plan"]["audience"]["tiers"]["cold"]["available"])
        self.assertFalse(stored["plan"]["audience"]["tiers"]["warm"]["available"])
        # 暫存批次選完就清掉，不留殘料
        self.assertEqual(ads_plan.get_pending_options(main.conn, self.bid, self.cycle_id), [])

    def test_selecting_a_non_recommended_option_by_id(self):
        self._generate()
        options = ads_plan.get_pending_options(main.conn, self.bid, self.cycle_id)
        other = next(o for o in options if not o["is_recommended"])
        self._select(option_id=other["id"])
        stored = ads_plan.get_latest_plan(main.conn, self.bid, self.cycle_id)
        self.assertEqual(stored["plan"]["summary"], _GOOD_OPTIONS["options"][1]["summary"])

    def test_selecting_unknown_option_id_fails_honestly(self):
        self._generate()
        resp = self._select(option_id="cpo_not_a_real_one")
        self.assertIn("kind=warn", resp.headers["location"])
        self.assertIsNone(ads_plan.get_latest_plan(main.conn, self.bid, self.cycle_id))

    def test_experiment_cells_created_one_per_angle(self):
        self._generate_and_select()
        rows = main.conn.execute(
            "SELECT * FROM experiment_cell WHERE campaign_cycle_id = ?", (self.cycle_id,)
        ).fetchall()
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["creative_angle"], "早上第一杯")
        self.assertIn("冷受眾", rows[0]["audience"])

    def test_hypotheses_go_to_brand_intelligence_and_are_linked(self):
        """策略假設住品牌智庫，廣告模組只透過連結表引用（鐵則 7）。"""
        self._generate_and_select()
        hypotheses = bi_repo.list_strategy_hypotheses(main.conn, self.bid)
        self.assertEqual(len(hypotheses), 2)
        links = main.conn.execute(
            "SELECT * FROM campaign_cycle_hypothesis WHERE campaign_cycle_id = ?",
            (self.cycle_id,)
        ).fetchall()
        self.assertEqual(len(links), 2)
        self.assertEqual({l["strategy_hypothesis_id"] for l in links},
                         {h["id"] for h in hypotheses})

    def test_numbers_are_given_to_model_not_asked_from_it(self):
        """決策 0016 硬性原則 4：預算數字由程式算好餵給模型，不要模型自己算。"""
        provider = FakeProvider(response=_fake(json.dumps(_GOOD_OPTIONS, ensure_ascii=False)))
        ads_plan.PROVIDER = provider
        _wait_progress(self.client,
                       f"/brands/{self.bid}/ads/{self.cycle_id}/plan/progress?run=1")
        sent = provider.calls[0]["messages"][0]["content"]
        self.assertIn("10,000", sent)
        self.assertIn("14 天", sent)
        self.assertIn("你不要重算", sent)

    def test_background_is_included_in_prompt_when_present(self):
        """票 3：開期背景欄落庫後，計畫生成的 prompt 要讀得到。"""
        resp = self.client.post(f"/brands/{self.bid}/ads/new",
                                data={"product_ids": [self.product], "slider_index": "5",
                                      "objective": "sales",
                                      "background": "母親節檔期，同業都在打折促銷。"},
                                follow_redirects=False)
        cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]
        provider = FakeProvider(response=_fake(json.dumps(_GOOD_OPTIONS, ensure_ascii=False)))
        ads_plan.PROVIDER = provider
        _wait_progress(self.client, f"/brands/{self.bid}/ads/{cycle_id}/plan/progress?run=1")
        sent = provider.calls[0]["messages"][0]["content"]
        self.assertIn("母親節檔期，同業都在打折促銷。", sent)

    def test_prompt_includes_methodology_content(self):
        """票 11：計畫生成的 prompt 要含對照表指定的方法論內容（ads/ab-testing/customer-voice）。"""
        provider = FakeProvider(response=_fake(json.dumps(_GOOD_OPTIONS, ensure_ascii=False)))
        ads_plan.PROVIDER = provider
        _wait_progress(self.client,
                       f"/brands/{self.bid}/ads/{self.cycle_id}/plan/progress?run=1")
        sent = provider.calls[0]["messages"][0]["content"]
        self.assertIn("【方法論：ads-core.md】", sent)
        self.assertIn("【方法論：ab-testing.md】", sent)
        self.assertIn("【方法論：customer-voice.md】", sent)
        # ads-core.md 內文一角，確認不是只帶檔名沒帶內容。
        # 這是承重字串：釘在 ads-core.md 第 1 節標題，改那個標題就要同步改這裡。
        self.assertIn("Meta 現行打法", sent)

        # ADR 0009：載入了哪幾個方法論檔要落進 llm_task 稽核，事後才回推得出來
        scope = json.loads(main.conn.execute(
            "SELECT context_scope_json FROM llm_task ORDER BY started_at DESC, id DESC LIMIT 1"
        ).fetchone()["context_scope_json"])
        self.assertIn("ads-core.md", scope["methodology_files"])
        self.assertIn("ab-testing.md", scope["methodology_files"])

    def test_include_methodology_false_skips_methodology_for_blind_test(self):
        """票 11 效果盲測：include_methodology=False 時同一條生產管線要略過方法論區塊，
        其餘上下文（受眾可用性、帳戶結構底案）不變——用來產生「接線前」對照組。"""
        provider = FakeProvider(response=_fake(json.dumps(_GOOD_OPTIONS, ensure_ascii=False)))
        ads_plan.PROVIDER = provider
        ok, err = ads_plan.generate_options(main.conn, self.bid, self.cycle_id, ACTOR,
                                            include_methodology=False)
        self.assertTrue(ok, err)
        sent = provider.calls[0]["messages"][0]["content"]
        self.assertNotIn("【方法論", sent)
        self.assertIn("冷受眾（陌生開發）：可用", sent)  # 其餘上下文照常組裝

    def test_prompt_includes_audience_availability_facts(self):
        """票 4：受眾三層可用性是程式算好的事實，告訴模型、不是問模型。"""
        provider = FakeProvider(response=_fake(json.dumps(_GOOD_OPTIONS, ensure_ascii=False)))
        ads_plan.PROVIDER = provider
        _wait_progress(self.client,
                       f"/brands/{self.bid}/ads/{self.cycle_id}/plan/progress?run=1")
        sent = provider.calls[0]["messages"][0]["content"]
        self.assertIn("冷受眾（陌生開發）：可用", sent)
        self.assertIn("暖受眾（再行銷）：這期不能用", sent)
        self.assertIn("還沒有廣告帶來過網站流量", sent)

    def test_prompt_includes_account_structure_budget_baseline(self):
        """票 5：帳戶結構與預算配置底案是程式算好的，告訴模型、不是問模型。
        pain_value 10,000／14 天 → 日預算約 714，落在中預算級距：CBO 兩組（驗證＋測試）。"""
        provider = FakeProvider(response=_fake(json.dumps(_GOOD_OPTIONS, ensure_ascii=False)))
        ads_plan.PROVIDER = provider
        _wait_progress(self.client,
                       f"/brands/{self.bid}/ads/{self.cycle_id}/plan/progress?run=1")
        sent = provider.calls[0]["messages"][0]["content"]
        self.assertIn("CBO，兩組（驗證＋測試）", sent)
        self.assertIn("70%", sent)
        self.assertIn("你不能改動這些數字", sent)

    def test_custom_direction_is_included_in_prompt(self):
        """票 4：方案選擇頁的自由輸入框——文字要真的送進 prompt，不是擺好看的。"""
        resp = self._generate(direction="想主打新品上市")
        self.assertEqual(resp.status_code, 303)
        sent = ads_plan.PROVIDER.calls[0]["messages"][0]["content"]
        self.assertIn("想主打新品上市", sent)

    def test_missing_methodology_file_does_not_block_and_is_shown_honestly(self):
        """票 11：方法論檔缺失時，流程照走、頁面誠實標注、audit 有紀錄。"""
        tmp_dir = Path(tempfile.mkdtemp(prefix="brand_os_methodology_"))
        # 故意不複製 ads-core.md，模擬缺檔；其餘全複製，這樣拆檔／加檔都不必回來改這裡
        for src in methodology.METHODOLOGY_DIR.glob("*.md"):
            if src.name != "ads-core.md":
                shutil.copy(src, tmp_dir / src.name)

        orig_dir = methodology.METHODOLOGY_DIR
        methodology.METHODOLOGY_DIR = tmp_dir
        try:
            resp = self._generate()
        finally:
            methodology.METHODOLOGY_DIR = orig_dir
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # 流程照走：方案仍然入庫，不因缺檔而失敗
        self.assertEqual(resp.status_code, 303)
        options = ads_plan.get_pending_options(main.conn, self.bid, self.cycle_id)
        self.assertTrue(options)
        self.assertEqual(options[0]["methodology_missing"], ["ads-core.md"])

        # 方案選擇頁誠實標注
        select_page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/plan/select")
        self.assertIn("ads-core.md", select_page.text)
        self.assertIn("方法論參考資料缺席", select_page.text)

        self._select()
        stored = ads_plan.get_latest_plan(main.conn, self.bid, self.cycle_id)
        self.assertEqual(stored["plan"]["methodology_missing"], ["ads-core.md"])

        # 選定後的檔期頁也誠實標注
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}")
        self.assertIn("ads-core.md", page.text)
        self.assertIn("方法論參考資料缺席", page.text)

        # audit 有紀錄
        rows = [dict(r) for r in main.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'methodology_file' AND entity_id = 'ads-core.md'"
        )]
        self.assertTrue(any(r["brand_id"] == self.bid for r in rows))
        self.assertEqual(rows[-1]["action"], "missing")

    def test_bad_json_does_not_store_any_option(self):
        resp = self._generate(reply="這期我建議先打通勤族，方案有兩個……")
        self.assertEqual(resp.status_code, 303)
        self.assertIn("kind=warn", resp.headers["location"])
        self.assertEqual(ads_plan.get_pending_options(main.conn, self.bid, self.cycle_id), [])
        self.assertIsNone(ads_plan.get_latest_plan(main.conn, self.bid, self.cycle_id))
        self.assertEqual(
            ads_repo.get_cycle(main.conn, self.bid, self.cycle_id)["status"], "PLANNING")

    def test_fewer_than_two_valid_options_is_rejected(self):
        resp = self._generate(reply=json.dumps(_INSUFFICIENT_OPTIONS, ensure_ascii=False))
        self.assertIn("kind=warn", resp.headers["location"])
        self.assertEqual(ads_plan.get_pending_options(main.conn, self.bid, self.cycle_id), [])

    def test_unavailable_tier_description_is_blanked_even_if_model_wrote_one(self):
        """就算模型硬寫了暖受眾描述，不可用的層也一律清空（程式的事實優先於模型判定）。"""
        tampered = json.loads(json.dumps(_GOOD_OPTIONS))
        tampered["options"][0]["audience"]["warm"]["description"] = "模型亂寫的暖受眾內容"
        self._generate(reply=json.dumps(tampered, ensure_ascii=False))
        options = ads_plan.get_pending_options(main.conn, self.bid, self.cycle_id)
        recommended = next(o for o in options if o["is_recommended"])
        self.assertEqual(recommended["audience"]["tiers"]["warm"]["description"], "")

    def test_exactly_one_recommended_is_enforced(self):
        """模型兩個方案都標推薦（不誠實）：程式要修正成剛好一個，不是照單全收。"""
        both_recommended = json.loads(json.dumps(_GOOD_OPTIONS))
        for option in both_recommended["options"]:
            option["is_recommended"] = True
        self._generate(reply=json.dumps(both_recommended, ensure_ascii=False))
        options = ads_plan.get_pending_options(main.conn, self.bid, self.cycle_id)
        self.assertEqual(sum(1 for o in options if o["is_recommended"]), 1)


class PlanBudgetCapTest(_BasePlanTest):
    """票 M2：計畫生成呼叫前先擋花費上限（原本 app/ads/plan.py 完全沒有這道檢查）。

    每個測試方法結束都把全域設定還原——這個設定跟其他測試共用同一個 main.conn，
    不還原會讓「調低上限」的測試把上限漏帶進後面其他測試（跨測試汙染）。
    """

    def setUp(self):
        super().setUp()
        self.addCleanup(coresettings.set_setting, main.conn, "intake_budget_limit", "30")

    def test_over_limit_blocks_before_calling_provider(self):
        coresettings.set_setting(main.conn, "intake_budget_limit", "0.0001")
        provider = FakeProvider(response=_fake(json.dumps(_GOOD_OPTIONS, ensure_ascii=False)))
        ads_plan.PROVIDER = provider
        ok, err = ads_plan.generate_options(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertFalse(ok)
        self.assertIn("US$", err)
        self.assertIn("花費上限", err)
        self.assertEqual(provider.calls, [])  # 真的沒送出呼叫，沒花到錢
        self.assertIsNone(ads_plan.get_latest_plan(main.conn, self.bid, self.cycle_id))

    def test_under_limit_still_generates_normally(self):
        coresettings.set_setting(main.conn, "intake_budget_limit", "1000")
        resp = self._generate()
        self.assertEqual(resp.status_code, 303)
        self.assertIn("/plan/select", resp.headers["location"])

    def test_shares_the_same_cap_as_intake_and_product_research(self):
        """M2 要求「同一道上限」：先用掉大半額度的是別的模組（模擬 llm_task 直接入庫），
        廣告計畫生成一樣要被擋，證明不是各模組各管各的。"""
        coresettings.set_setting(main.conn, "intake_budget_limit", "1.00")
        main.conn.execute(
            "INSERT INTO llm_task (id, brand_id, task_type, context_scope_json,"
            " input_context_ids_json, input_context_hash, knowledge_item_ids_json,"
            " brand_version, prompt_template_id, prompt_template_version, provider, model,"
            " status, attempt_no, cost, started_at, finished_at)"
            " VALUES (?, ?, 'intake_scan', '{}', '[]', '', '[]', 1, 'p', 'v1', 'seed', 'seed',"
            " 'succeeded', 1, 0.90, ?, ?)",
            (new_id("llm"), self.bid, now_iso(), now_iso()),
        )
        main.conn.commit()
        provider = FakeProvider(response=_fake(json.dumps(_GOOD_OPTIONS, ensure_ascii=False)))
        ads_plan.PROVIDER = provider
        ok, err = ads_plan.generate_options(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertFalse(ok, err)
        self.assertEqual(provider.calls, [])


class AudienceAvailabilityTest(unittest.TestCase):
    """純函數：受眾三層可用性由品牌歷史成效資料算出，不問模型。"""

    def setUp(self):
        self.brand = bi_repo.create_brand(main.conn, name="虛構受眾測試品牌",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]

    def test_cold_always_available_warm_and_hot_default_unavailable(self):
        availability = ads_plan.audience_availability(main.conn, self.bid)
        self.assertTrue(availability["cold"]["available"])
        self.assertFalse(availability["warm"]["available"])
        self.assertFalse(availability["hot"]["available"])

    def test_warm_available_once_there_is_traffic(self):
        _seed_snapshot(self.bid, clicks=50, conversions=0)
        availability = ads_plan.audience_availability(main.conn, self.bid)
        self.assertTrue(availability["warm"]["available"])
        self.assertFalse(availability["hot"]["available"])

    def test_hot_available_once_there_are_conversions(self):
        _seed_snapshot(self.bid, clicks=50, conversions=3)
        availability = ads_plan.audience_availability(main.conn, self.bid)
        self.assertTrue(availability["hot"]["available"])


class PlanPageTest(_BasePlanTest):
    def test_page_shows_plan_split_by_grounding(self):
        self._generate_and_select()
        resp = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}")
        self.assertIn("早上第一杯", resp.text)
        self.assertIn("依據已確認的品牌資料", resp.text)
        self.assertIn("AI 自己的推論", resp.text)
        self.assertIn("未經證實", resp.text)
        self.assertIn("要靠這期投放才知道的事", resp.text)

    def test_page_shows_structured_audience_tiers(self):
        self._generate_and_select()
        resp = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}")
        self.assertIn("冷受眾（陌生開發）", resp.text)
        self.assertIn("暖受眾（再行銷）", resp.text)
        self.assertIn("這期用不到", resp.text)
        self.assertIn("還沒有廣告帶來過網站流量", resp.text)

    def test_select_page_shows_recommended_badge_and_difference(self):
        self._generate()
        resp = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/plan/select")
        self.assertIn("AI 推薦", resp.text)
        self.assertIn("主打通勤族的省錢與快速訴求", resp.text)
        self.assertIn("不打通勤族，改打願意為風味付費的鑑賞型客群", resp.text)

    def test_gate_appears_only_in_review(self):
        before = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}")
        self.assertIn("產出這期的方案", before.text)
        self.assertNotIn("就照這個做", before.text)

        self._generate()
        waiting = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}")
        self.assertIn("去選方案", waiting.text)
        self.assertNotIn("就照這個做", waiting.text)

        self._select()
        after = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}")
        self.assertIn("就照這個做", after.text)


class PlanApprovalTest(_BasePlanTest):
    def test_approval_freezes_plan_and_advances_cycle(self):
        self._generate_and_select()
        resp = self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/plan/approve",
                                follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        stored = ads_plan.get_latest_plan(main.conn, self.bid, self.cycle_id)
        self.assertEqual(stored["status"], "approved")
        self.assertEqual(stored["approved_by"], OPERATOR)
        self.assertEqual(
            ads_repo.get_cycle(main.conn, self.bid, self.cycle_id)["status"], "PRODUCTION")

    def test_cannot_approve_without_a_plan(self):
        resp = self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/plan/approve",
                                follow_redirects=False)
        self.assertIn("kind=warn", resp.headers["location"])
        self.assertEqual(
            ads_repo.get_cycle(main.conn, self.bid, self.cycle_id)["status"], "PLANNING")

    def test_approval_works_without_operator_cookie(self):
        """ADR 0004：關卡一（計畫確認）仍要人按一次確認，但不再要求先設定操作人。"""
        self._generate_and_select()
        self.client.cookies.clear()
        resp = self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/plan/approve",
                                follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertNotIn("/settings/operator", resp.headers["location"])
        stored = ads_plan.get_latest_plan(main.conn, self.bid, self.cycle_id)
        self.assertEqual(stored["status"], "approved")
        self.assertEqual(stored["approved_by"], OPERATOR)
        self.assertEqual(
            ads_repo.get_cycle(main.conn, self.bid, self.cycle_id)["status"], "PRODUCTION")

    def test_regenerating_after_approval_creates_new_version(self):
        self._generate_and_select()
        self._generate_and_select()
        rows = main.conn.execute(
            "SELECT plan_version FROM campaign_plan WHERE campaign_cycle_id = ?"
            " ORDER BY plan_version", (self.cycle_id,)
        ).fetchall()
        self.assertEqual([r["plan_version"] for r in rows], [1, 2])

    def test_regenerating_before_selection_replaces_pending_options(self):
        """還沒選定就重新生成：舊的暫存方案整批換掉，不會累積、也不會偷偷落地。"""
        self._generate()
        first_batch_ids = {o["id"] for o in
                           ads_plan.get_pending_options(main.conn, self.bid, self.cycle_id)}
        self._generate()
        second_batch = ads_plan.get_pending_options(main.conn, self.bid, self.cycle_id)
        self.assertEqual(len(second_batch), 2)
        self.assertFalse({o["id"] for o in second_batch} & first_batch_ids)
        self.assertIsNone(ads_plan.get_latest_plan(main.conn, self.bid, self.cycle_id))


class DissentTest(_BasePlanTest):
    """票 5：AI 對帳戶結構／預算配置底案、或明顯薄弱的 Offer 提出的具名異議。

    三種 target（account_structure/budget_allocation/offer）共用同一套正規化與落庫邏輯，
    Offer 薄弱偵測不是另一套機制（決策 0024 第 5 點：過渡做法，走既定異議機制）。
    """

    def test_dissents_are_parsed_and_persisted_as_pending(self):
        self._generate(reply=_with_dissents(*_DISSENT_ITEMS))
        dissents = ads_repo.list_dissents(main.conn, self.bid, self.cycle_id)
        self.assertEqual(len(dissents), 3)
        self.assertEqual({d["target_type"] for d in dissents},
                         {"account_structure", "budget_allocation", "offer"})
        self.assertTrue(all(d["status"] == "pending" for d in dissents))
        self.assertTrue(all(d["suggestion"] and d["reason"] for d in dissents))

    def test_no_dissents_key_means_no_opinion_not_a_crash(self):
        """模型沒有意見（或整個沒回這個欄位）：流程照走，異議清單就是空的。"""
        resp = self._generate()  # _GOOD_OPTIONS 本來就沒有 dissents 欄位
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(ads_repo.list_dissents(main.conn, self.bid, self.cycle_id), [])

    def test_invalid_target_is_dropped(self):
        bad = {"target": "隨便亂寫的目標", "suggestion": "x", "reason": "y"}
        self._generate(reply=_with_dissents(bad, _DISSENT_ITEMS[0]))
        dissents = ads_repo.list_dissents(main.conn, self.bid, self.cycle_id)
        self.assertEqual(len(dissents), 1)
        self.assertEqual(dissents[0]["target_type"], "account_structure")

    def test_missing_reason_or_suggestion_is_dropped(self):
        no_reason = {"target": "offer", "suggestion": "有建議但沒理由", "reason": ""}
        no_suggestion = {"target": "offer", "suggestion": "", "reason": "有理由但沒建議"}
        self._generate(reply=_with_dissents(no_reason, no_suggestion))
        self.assertEqual(ads_repo.list_dissents(main.conn, self.bid, self.cycle_id), [])

    def test_dissent_count_is_capped(self):
        four = _DISSENT_ITEMS + [
            {"target": "offer", "suggestion": "第四條", "reason": "超過上限的那條"},
        ]
        self._generate(reply=_with_dissents(*four))
        self.assertEqual(len(ads_repo.list_dissents(main.conn, self.bid, self.cycle_id)), 3)

    def test_regenerating_replaces_pending_but_keeps_decided(self):
        """重新生成方案：還沒被老闆處理過的舊異議整批換掉；已經決定過的留著，供事後驗證。"""
        self._generate(reply=_with_dissents(*_DISSENT_ITEMS))
        first_batch = ads_repo.list_dissents(main.conn, self.bid, self.cycle_id)
        decided_id = first_batch[0]["id"]
        ads_repo.decide_dissent(main.conn, self.bid, self.cycle_id, decided_id, "adopted",
                                actor=ACTOR)

        self._generate(reply=_with_dissents(_DISSENT_ITEMS[1]))
        after = ads_repo.list_dissents(main.conn, self.bid, self.cycle_id)
        self.assertIn(decided_id, {d["id"] for d in after})
        decided_row = next(d for d in after if d["id"] == decided_id)
        self.assertEqual(decided_row["status"], "adopted")
        self.assertEqual(decided_row["decided_by"], ACTOR)
        pending_rows = [d for d in after if d["status"] == "pending"]
        self.assertEqual(len(pending_rows), 1)

    def test_select_page_shows_baseline_and_dissents(self):
        self._generate(reply=_with_dissents(*_DISSENT_ITEMS))
        resp = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/plan/select")
        self.assertIn("這期的帳戶結構與預算配置底案", resp.text)
        self.assertIn("CBO，兩組（驗證＋測試）", resp.text)
        self.assertIn("AI 對底案的異議", resp.text)
        self.assertIn(_DISSENT_ITEMS[0]["suggestion"], resp.text)
        self.assertIn(_DISSENT_ITEMS[0]["reason"], resp.text)
        self.assertIn("這期的 Offer", resp.text)  # target_type=offer 的人話標籤

    def test_select_page_hides_dissent_block_when_none(self):
        self._generate()  # 沒有異議
        resp = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/plan/select")
        self.assertNotIn("AI 對底案的異議", resp.text)

    def test_decide_dissent_records_status_and_actor(self):
        self._generate(reply=_with_dissents(*_DISSENT_ITEMS))
        dissent_id = ads_repo.list_dissents(main.conn, self.bid, self.cycle_id)[0]["id"]
        resp = self.client.post(
            f"/brands/{self.bid}/ads/{self.cycle_id}/dissents/{dissent_id}/decide",
            data={"decision": "adopted"}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        updated = next(d for d in ads_repo.list_dissents(main.conn, self.bid, self.cycle_id)
                      if d["id"] == dissent_id)
        self.assertEqual(updated["status"], "adopted")
        self.assertEqual(updated["decided_by"], OPERATOR)
        self.assertIsNotNone(updated["decided_at"])

    def test_decide_works_without_operator_cookie(self):
        """ADR 0004：異議採納決定不再要求先設定操作人，稽核仍記下固定的操作人值。"""
        self._generate(reply=_with_dissents(*_DISSENT_ITEMS))
        dissent_id = ads_repo.list_dissents(main.conn, self.bid, self.cycle_id)[0]["id"]
        self.client.cookies.clear()
        resp = self.client.post(
            f"/brands/{self.bid}/ads/{self.cycle_id}/dissents/{dissent_id}/decide",
            data={"decision": "adopted"}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertNotIn("/settings/operator", resp.headers["location"])
        updated = next(d for d in ads_repo.list_dissents(main.conn, self.bid, self.cycle_id)
                      if d["id"] == dissent_id)
        self.assertEqual(updated["status"], "adopted")
        self.assertEqual(updated["decided_by"], OPERATOR)

    def test_decide_unknown_dissent_id_fails_honestly(self):
        self._generate(reply=_with_dissents(*_DISSENT_ITEMS))
        resp = self.client.post(
            f"/brands/{self.bid}/ads/{self.cycle_id}/dissents/dsn_not_real/decide",
            data={"decision": "adopted"}, follow_redirects=False)
        self.assertIn("kind=warn", resp.headers["location"])


if __name__ == "__main__":
    unittest.main()
