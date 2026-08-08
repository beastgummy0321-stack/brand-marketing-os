# -*- coding: utf-8 -*-
"""app/tests/test_video_theme.py — 影片腳本主題端到端（票 08-video-theme）。

接縫一（引擎門口，app/ads/theme_engine_video.py generate_video_theme／combine_video_script）：
假簡報進 → 驗 3 支腳本（框架互異至少 2 種）＋切角層共用 10 個 Hook（第二支不重生）＋
5/5/5 文字，數量與字數對規格表；驗腳本×Hook 組合輸出。字數守門與相似度標黃直接呼叫
theme_engine 的既有兩道通用守門（不另寫），這裡只驗「video 有沿用到」，不重測守門本身
的邏輯（那是 test_char_guard.py／SimilarityFlagTest 的範圍）。全程 FakeProvider，不發任何
真實網路請求。品牌與產品名一律虛構。setUp／_ready_cell 等寫法照抄
app/tests/test_carousel_theme.py（票 07）——本專案測試檔一律自帶獨立 tmp DB，不共用 import。
"""

import atexit
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_video_theme_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import brief_assembler  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.ads import theme_engine  # noqa: E402
from app.ads import theme_engine_video  # noqa: E402
from app.ads import theme_repository as theme_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import creative_assets  # noqa: E402
from app.core import db  # noqa: E402
from app.core import settings as coresettings  # noqa: E402
from app.creative.format_specs import FORMAT_SPECS  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402

main.reopen_connection()

ROOT = Path(_tmpdir) / "creative"


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"
_FIELDS = FORMAT_SPECS["video"]["fields"]
_AXES_VALUES = {"angle": "benefit", "tone": "warm", "format": "video",
                "selling_point": "quality"}
_HOOKS = [f"Hook{i}：候選台詞{i}" for i in range(10)]


def _fake(text: str) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=400, output_tokens=250),
                            stop_reason="end_turn")


def _text_item(label: str, i: int) -> dict:
    return {"content": f"{label}{i}", "fingerprint": _AXES_VALUES}


def _video_reply(*, framework: str, name: str = "虛構主題：送禮不失禮",
                 hook_pool=None, segment_labels=None, first_segment_dialogue=None,
                 body_items=None, extra_top: dict = None) -> str:
    segment_labels = segment_labels or ["痛點", "加壓", "解方", "行動"]
    segments = [{"label": label, "dialogue": f"{label}台詞", "visual": f"{label}畫面"}
               for label in segment_labels]
    if first_segment_dialogue is not None:
        segments[0]["dialogue"] = first_segment_dialogue
    payload = {
        "name": name,
        "framework": framework,
        "segments": segments,
        "body": body_items if body_items is not None else [_text_item("文案", i) for i in range(5)],
        "title": [_text_item("標題", i) for i in range(5)],
        "description": [_text_item("說明", i) for i in range(5)],
    }
    if hook_pool is not None:
        payload["hook_pool"] = hook_pool
    if extra_top:
        payload.update(extra_top)
    return json.dumps(payload, ensure_ascii=False)


class _SequencedProvider:
    """依序回傳不同回覆的假 Provider（照抄 app/tests/test_char_guard.py 同名類別）：
    第一次呼叫＝主生成，第二次以後＝字數守門的重寫呼叫。"""

    name = "fake-sequenced"

    def __init__(self, replies: list):
        self._responses = [_fake(text) for text in replies]
        self.calls: list = []

    def complete(self, *, model, system, messages, max_tokens, timeout_s=120.0):
        self.calls.append({"model": model, "system": system, "messages": messages,
                           "max_tokens": max_tokens, "timeout_s": timeout_s})
        index = min(len(self.calls) - 1, len(self._responses) - 1)
        return self._responses[index]


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        coresettings.set_setting(main.conn, creative_assets.SETTING_KEY, str(ROOT))
        coresettings.set_setting(main.conn, "intake_budget_limit", "1000")
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡（影片票）",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        self.product_id = bi_repo.create_product(main.conn, self.bid, name="虛構濾掛組",
                                                  actor=ACTOR)["id"]
        self._orig_provider = theme_engine.PROVIDER

    def tearDown(self):
        theme_engine.PROVIDER = self._orig_provider
        coresettings.set_setting(main.conn, "intake_budget_limit", "30")

    def _ready_cell(self, *, objective: str = "sales") -> tuple:
        cycle = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[self.product_id],
            pain_value=5, objective=objective, actor=ACTOR,
        )
        cycle_id = cycle["id"]
        cell_id = db.new_id("exc")
        main.conn.execute(
            "INSERT INTO experiment_cell (id, campaign_cycle_id, brand_id, product_id,"
            " creative_angle, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (cell_id, cycle_id, self.bid, self.product_id, "送禮情境：怕失禮",
             db.now_iso()),
        )
        main.conn.execute(
            "INSERT INTO campaign_plan (id, campaign_cycle_id, brand_id, plan_version,"
            " plan_json, status, approved_by, approved_at, created_at)"
            " VALUES (?, ?, ?, ?, ?, 'approved', ?, ?, ?)",
            (db.new_id("cpl"), cycle_id, self.bid, 1,
             json.dumps({"summary": "測試打法：送禮不失禮"}, ensure_ascii=False),
             ACTOR, db.now_iso(), db.now_iso()),
        )
        main.conn.commit()
        return cycle_id, cell_id

    def _assemble(self, cycle_id: str, cell_id: str):
        brief, err = brief_assembler.assemble_brief(
            main.conn, self.bid, cycle_id, cell_id, "video", theme_count=1, actor=ACTOR)
        self.assertIsNone(err, err)
        return brief

    def _swap(self, reply: str) -> FakeProvider:
        provider = FakeProvider(response=_fake(reply))
        theme_engine.PROVIDER = provider
        return provider

    def _generate_and_save(self, cycle_id, cell_id, *, framework: str, hook_pool=None,
                           **reply_kwargs):
        brief = self._assemble(cycle_id, cell_id)
        self._swap(_video_reply(framework=framework, hook_pool=hook_pool, **reply_kwargs))
        generated, err = theme_engine_video.generate_video_theme(main.conn, brief, actor=ACTOR)
        self.assertIsNone(err, err)
        return theme_engine.save_generated_theme(main.conn, brief, generated, actor=ACTOR)


class ThreeScriptsSharedHookPoolTest(_Base):
    """票 08 驗收 1、2、4：假簡報進 → 3 腳本（框架標記互異至少 2 種）＋切角層共用 10 個
    Hook（第二支不重生）＋5/5/5 文字；腳本＝主題，一支一列。"""

    def test_three_calls_produce_three_theme_rows_two_frameworks_and_one_shared_pool(self):
        cycle_id, cell_id = self._ready_cell()

        theme1 = self._generate_and_save(
            cycle_id, cell_id, framework="PAS", hook_pool=list(_HOOKS))
        prompt1 = theme_engine.PROVIDER.calls[0]["messages"][0]["content"]

        theme2 = self._generate_and_save(cycle_id, cell_id, framework="AIDA")
        prompt2 = theme_engine.PROVIDER.calls[0]["messages"][0]["content"]

        theme3 = self._generate_and_save(cycle_id, cell_id, framework="PAS")

        # 腳本＝主題：3 次呼叫存出 3 列不同的主題資料。
        self.assertEqual(len({theme1["id"], theme2["id"], theme3["id"]}), 3)
        for theme in (theme1, theme2, theme3):
            self.assertEqual(theme["format_key"], "video")

        def _framework_of(theme):
            script = next(c for c in theme["components"] if c["component_type"] == "script")
            return json.loads(script["content"])["framework"]

        frameworks = {_framework_of(t) for t in (theme1, theme2, theme3)}
        self.assertGreaterEqual(len(frameworks), 2)

        # Hook 池掛切角層：只有第一支腳本落了 10 個 hook_pool 元件，第二、三支零個
        # （不重生、不重複落庫）。
        def _hook_count(theme):
            return len([c for c in theme["components"] if c["component_type"] == "hook_pool"])

        self.assertEqual(_hook_count(theme1), 10)
        self.assertEqual(_hook_count(theme2), 0)
        self.assertEqual(_hook_count(theme3), 0)

        # 5/5/5 文字（重用單圖規則），每支腳本各自都有一份。
        for theme in (theme1, theme2, theme3):
            for field in ("body", "title", "description"):
                count = len([c for c in theme["components"] if c["component_type"] == field])
                self.assertEqual(count, _FIELDS[field]["count"])

        # 第一次呼叫的 prompt 有要求 10 個 Hook；第二次呼叫改成告知已有 Hook 池、不再問。
        self.assertIn(f"{_FIELDS['hook_pool']['count']} 個 Hook", prompt1)
        self.assertIn("已經有共用的 Hook 池了，不用你再生 Hook", prompt2)
        self.assertIn(_HOOKS[0], prompt2)  # 既有 Hook 內容有餵回給第二支腳本當參考

    def test_wrong_format_key_on_brief_raises(self):
        cycle_id, cell_id = self._ready_cell()
        brief, err = brief_assembler.assemble_brief(
            main.conn, self.bid, cycle_id, cell_id, "single_image", theme_count=1, actor=ACTOR)
        self.assertIsNone(err, err)
        with self.assertRaises(ValueError):
            theme_engine_video.generate_video_theme(main.conn, brief, actor=ACTOR)

    def test_prompt_forbids_cta_and_link(self):
        cycle_id, cell_id = self._ready_cell()
        brief = self._assemble(cycle_id, cell_id)
        provider = self._swap(_video_reply(framework="PAS", hook_pool=list(_HOOKS)))
        theme_engine_video.generate_video_theme(main.conn, brief, actor=ACTOR)
        prompt_text = provider.calls[0]["messages"][0]["content"]
        self.assertIn("不要生成任何 CTA", prompt_text)


class HookSlotAlwaysPlaceholderTest(_Base):
    """方法論規則「Hook 段一律留插槽，不寫死」由程式碼強制：即使 AI 自己寫了台詞，
    第一段的台詞照樣被蓋成插槽佔位字串。"""

    def test_first_segment_dialogue_is_overridden_even_when_model_writes_one(self):
        cycle_id, cell_id = self._ready_cell()
        brief = self._assemble(cycle_id, cell_id)
        self._swap(_video_reply(
            framework="PAS", hook_pool=list(_HOOKS),
            first_segment_dialogue="這句是 AI 自己寫的開場台詞，不應該留下來"))

        generated, err = theme_engine_video.generate_video_theme(main.conn, brief, actor=ACTOR)
        self.assertIsNone(err, err)
        script = json.loads(
            next(c for c in generated["components"] if c["component_type"] == "script")["content"])
        self.assertEqual(script["segments"][0]["dialogue"], theme_engine_video.HOOK_SLOT_PLACEHOLDER)
        self.assertNotIn("這句是 AI 自己寫的開場台詞", script["segments"][0]["dialogue"])
        # 後面段落的台詞不受影響，照樣留著。
        self.assertEqual(script["segments"][1]["dialogue"], "加壓台詞")


class CombineScriptTest(_Base):
    """票 08 驗收 3：給腳本 id＋Hook id → 回完整腳本（Hook 已套入插槽），9:16／30 秒基準
    資訊來自規格表。"""

    def test_combine_substitutes_hook_into_first_segment(self):
        cycle_id, cell_id = self._ready_cell()
        theme = self._generate_and_save(
            cycle_id, cell_id, framework="帶貨五段式",
            segment_labels=["鉤子", "展示", "賣點", "信任", "轉化"],
            hook_pool=list(_HOOKS))
        hook_component = next(
            c for c in theme["components"]
            if c["component_type"] == "hook_pool" and c["content"] == _HOOKS[3])

        text, err = theme_engine_video.combine_video_script(
            main.conn, self.bid, theme["id"], hook_component["id"])
        self.assertIsNone(err, err)

        spec = FORMAT_SPECS["video"]
        self.assertIn(spec["ratio"], text)
        self.assertIn(str(spec["duration_seconds_default"]), text)
        self.assertIn(_HOOKS[3], text)
        self.assertNotIn(theme_engine_video.HOOK_SLOT_PLACEHOLDER, text)
        self.assertIn("鉤子：" + _HOOKS[3], text)
        self.assertIn("展示：展示台詞", text)  # 其餘段落原樣保留

    def test_unknown_theme_returns_error(self):
        text, err = theme_engine_video.combine_video_script(
            main.conn, self.bid, "cth_not_real", "cthc_not_real")
        self.assertIsNone(text)
        self.assertIn("找不到", err)

    def test_unknown_hook_id_returns_error(self):
        cycle_id, cell_id = self._ready_cell()
        theme = self._generate_and_save(
            cycle_id, cell_id, framework="PAS", hook_pool=list(_HOOKS))
        text, err = theme_engine_video.combine_video_script(
            main.conn, self.bid, theme["id"], "cthc_not_real")
        self.assertIsNone(text)
        self.assertIn("找不到這個 Hook", err)

    def test_non_video_theme_returns_error(self):
        cycle_id, cell_id = self._ready_cell()
        theme_repo.create_theme(
            main.conn, self.bid, campaign_cycle_id=cycle_id, experiment_cell_id=cell_id,
            format_key="single_image", name="虛構主題：不是影片", folder_code="Z9Z9",
            actor=ACTOR,
            components=[{"component_type": "body", "content": "不是影片主題"}],
        )
        single_image_theme = theme_repo.list_themes_for_cell(main.conn, self.bid, cell_id)[0]
        text, err = theme_engine_video.combine_video_script(
            main.conn, self.bid, single_image_theme["id"], "cthc_not_real")
        self.assertIsNone(text)
        self.assertIn("找不到這支影片腳本主題", err)


class CharGuardAndSimilarityReuseTest(_Base):
    """字數守門與相似度標黃必須沿用 theme_engine 既有兩道通用守門，不得另寫。"""

    def test_over_budget_body_triggers_shared_char_rewrite(self):
        cycle_id, cell_id = self._ready_cell()
        brief = self._assemble(cycle_id, cell_id)
        long_body = "超字警報" * 40  # 遠超 body 125 字預算
        short_rewrite = "已經壓過一次的短文案，還是很吸引人的送禮首選"
        body_items = [{"content": long_body, "fingerprint": _AXES_VALUES}] + [
            _text_item("文案", i) for i in range(1, 5)]

        provider = _SequencedProvider([
            _video_reply(framework="PAS", hook_pool=list(_HOOKS), body_items=body_items),
            json.dumps({"rewrites": [short_rewrite]}, ensure_ascii=False),
        ])
        theme_engine.PROVIDER = provider

        generated, err = theme_engine_video.generate_video_theme(main.conn, brief, actor=ACTOR)
        self.assertIsNone(err, err)
        self.assertEqual(len(provider.calls), 2)  # 主生成 1 次＋重寫 1 次
        body = [c for c in generated["components"] if c["component_type"] == "body"]
        rewritten = next(c for c in body if c["content"] == short_rewrite)
        self.assertFalse(rewritten.get("over_budget"))

    def test_similarity_flag_applies_to_body_not_to_script_or_hooks(self):
        cycle_id, cell_id = self._ready_cell()
        brief = self._assemble(cycle_id, cell_id)
        body_items = [_text_item("文案", i) for i in range(5)]  # 全部同指紋 → 一定標黃
        self._swap(_video_reply(
            framework="PAS", hook_pool=list(_HOOKS), body_items=body_items))

        generated, err = theme_engine_video.generate_video_theme(main.conn, brief, actor=ACTOR)
        self.assertIsNone(err, err)
        body = [c for c in generated["components"] if c["component_type"] == "body"]
        self.assertTrue(any(c.get("similarity_flag") for c in body))
        others = [c for c in generated["components"]
                 if c["component_type"] in ("script", "hook_pool")]
        self.assertFalse(any(c.get("similarity_flag") for c in others))


class RouteGenerateVideoThemeTest(_Base):
    """接縫二（路由層）：video 掛進 routes_creative_theme.py 合併的 GENERATORS 表，
    走跟單圖／輪播同一條存檔與路由路徑。"""

    def test_post_returns_json_video_theme(self):
        cycle_id, cell_id = self._ready_cell()
        self._swap(_video_reply(
            framework="PAS", hook_pool=list(_HOOKS), name="虛構主題：送禮不失禮"))

        resp = self.client.post(
            f"/api/ads/brands/{self.bid}/ads/{cycle_id}/cells/{cell_id}"
            f"/formats/video/themes")
        self.assertEqual(resp.status_code, 200)
        theme = resp.json()["theme"]
        self.assertEqual(theme["name"], "虛構主題：送禮不失禮")
        self.assertEqual(theme["format_key"], "video")
        self.assertEqual(theme["status"], "draft")
        # 1 腳本 ＋ 10 hook_pool ＋ 5 body ＋ 5 title ＋ 5 description ＝ 26
        self.assertEqual(len(theme["components"]), 26)
        self.assertTrue(Path(theme["folder_path"]).is_dir())


if __name__ == "__main__":
    unittest.main()
