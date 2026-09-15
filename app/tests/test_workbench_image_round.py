"""app/tests/test_workbench_image_round.py — F07-I07 (ARCHITECTURE.md §5.7-§5.10): one round
of image prompts is one model call that writes exactly 10 items (or 2 carousel concepts), each
slot's look assigned by the program, the brand's derived identity and look texture appended,
and stored as its own version row with a fingerprint and a recommendation.

FakeProvider only, no real network request; CI never calls a model.
"""

import json
import random
import re
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import app.background as background_module
import app.main as main
import app.shared.web as web
import app.workbench as workbench_module
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.llm import providers
from app.workbench import jobs as workbench_jobs
from app.workbench import looks as looks_mod
from app.workbench import prompts as workbench_prompts
from app.workbench import repository as workbench_repo
from app.workbench import visual

ACTOR = "測試員"

_LOOK_LINE_RE = re.compile(r"- 第 (\d+) [則組]：([a-zA-Z_]+)（")
_DEVICE_CYCLE = list(visual.DEVICES)
_LAYOUT_CYCLE = list(visual.LAYOUTS)


def _identity_reply(**overrides) -> dict:
    base = {
        "identity": "都會生活感，人物二十到三十五歲，配色暖米大地色，情緒放鬆自在。",
        "fit_looks": ["soft_lifestyle", "documentary", "clean_bright"],
        "excluded_looks": [], "reason": "依品牌事實推導。",
    }
    base.update(overrides)
    return base


def _item(i: int, look: str, *, subject_role="clear", persuasion="none") -> dict:
    headline = f"文案{i}號"
    return {
        "title": f"點子{i}", "device": _DEVICE_CYCLE[i % len(_DEVICE_CYCLE)],
        "layout": _LAYOUT_CYCLE[i % len(_LAYOUT_CYCLE)], "look": look,
        "subject_role": subject_role, "persuasion": persuasion, "headline": [headline],
        "prompt": (
            f"4:5 直式單圖廣告，情境示意畫面第 {i} 則，人物在明亮廚房裡拿著商品。"
            f"主標「{headline}」置中，純色填滿，不放其他文字。"
        ),
    }


def _card(n: int, concept: int) -> dict:
    headline = f"卡{concept}之{n}"
    return {
        "headline": [headline],
        "prompt": (
            f"1:1 輪播卡片，第 {concept} 組第 {n} 張，情境畫面延續同一個人物與版型。"
            f"主標「{headline}」置中，純色填滿。"
        ),
    }


def _concept(c: int, look: str, *, subject_role="clear", persuasion="none") -> dict:
    return {
        "title": f"概念{c}", "device": _DEVICE_CYCLE[c % len(_DEVICE_CYCLE)],
        "layout": _LAYOUT_CYCLE[c % len(_LAYOUT_CYCLE)], "look": look,
        "subject_role": subject_role, "persuasion": persuasion,
        "cards": [_card(n, c) for n in range(1, 6)],
    }


class _ImageProvider:
    """一個假供應商同時扮 `workbench_derive_identity`（識別）跟 `workbench_image_prompt`
    （每一輪一次，或加一次修正輪）——靠 prompt 內容分辨是哪一通：識別部門檔開頭是
    「品牌視覺總監」；修正輪的 `fix.md` 固定帶「這些欄位沒有通過驗證，只重新回答這些」；
    其餘就是正輪，讀 worksheet 的「- 第 N 則／組：<look>」把系統分配的風格填回每一項的
    `look`（票面 Done：讀 worksheet 分配、寫回 item 的 `look`）。"""

    name = "fake"

    def __init__(self, *, identity: dict, image_task: str = "believe_solution",
                 shape: str = "single", fix: dict | None = None,
                 subject_role: str = "clear", persuasion: str = "none",
                 warnings: list | None = None):
        self._identity = identity
        self._image_task = image_task
        self._shape = shape
        self._fix = fix
        self._subject_role = subject_role
        self._persuasion = persuasion
        self._warnings = warnings if warnings is not None else ["w1"]
        self.calls: list = []
        self.tool_calls: list = []

    def _image_reply(self, text: str) -> dict:
        plan = {int(n): look for n, look in _LOOK_LINE_RE.findall(text)}
        if self._shape == "single":
            items = [
                _item(i, plan.get(i, "soft_lifestyle"), subject_role=self._subject_role,
                      persuasion=self._persuasion)
                for i in range(1, 11)
            ]
            reply: dict = {"items": items, "warnings": list(self._warnings)}
        else:
            concepts = [
                _concept(c, plan.get(c, "soft_lifestyle"), subject_role=self._subject_role,
                         persuasion=self._persuasion)
                for c in range(1, 3)
            ]
            reply = {"concepts": concepts, "warnings": list(self._warnings)}
        reply["image_task"] = self._image_task
        return reply

    def complete(self, *, model, system, messages, max_tokens, timeout_s=120.0,
                 effort=None, tools=None, org_id=None) -> providers.ProviderResponse:
        text = messages[0]["content"]
        self.calls.append(text)
        self.tool_calls.append(tools)
        if "品牌視覺總監" in text:
            return providers.ProviderResponse(
                output_text="", structured=self._identity,
                usage=providers.Usage(input_tokens=500, output_tokens=200), stop_reason="end_turn",
            )
        if "這些欄位沒有通過驗證，只重新回答這些" in text and self._fix is not None:
            return providers.ProviderResponse(
                output_text=json.dumps(self._fix, ensure_ascii=False), structured=None,
                usage=providers.Usage(input_tokens=500, output_tokens=200), stop_reason="end_turn",
            )
        return providers.ProviderResponse(
            output_text="", structured=self._image_reply(text),
            usage=providers.Usage(input_tokens=500, output_tokens=200), stop_reason="end_turn",
        )


class _ImageRoundTestBase(unittest.TestCase):
    def setUp(self):
        workbench_module.register_tasks()
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：圖片提示詞回合", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        self.product = bi_repo.create_product(
            web.conn, self.brand_id, name="測試產品：晨光咖啡豆", actor=ACTOR,
        )
        web.conn.commit()
        resp = TestClient(main.app).get(
            f"/api/schedule/brands/{self.brand_id}/coordinates"
        )
        assert resp.status_code == 200, resp.text
        self.coordinate_rows = workbench_repo.list_coordinate_vocabulary(
            web.conn, self.org_id, self.brand_id
        )
        self._orig_provider = workbench_jobs.PROVIDER

    def tearDown(self):
        workbench_jobs.PROVIDER = self._orig_provider

    def _key_row(self, dimension: str, key: str) -> dict:
        return next(
            r for r in self.coordinate_rows if r["dimension"] == dimension and r["key"] == key
        )

    def _run_worker(self) -> None:
        web.conn.commit()
        background_module.app().run_worker(wait=False)

    def _submit(self, **overrides) -> str:
        brief = {
            "source_kind": "manual", "source_ref": {},
            "product_id": self.product["id"], "coordinates": {}, "visual_tone": None,
            "visual_concept": None, "style_key": "ugc",
            "request": {"parts": ["image_prompt"]},
        }
        brief.update(overrides)
        return workbench_repo.create_brief(web.conn, self.org_id, self.brand_id, brief)

    def _outputs(self, brief_id: str) -> list:
        rows = web.conn.execute(
            "SELECT * FROM workbench_output WHERE brief_id = %s AND part = 'image_prompt'"
            " ORDER BY generation_round, version_index", (brief_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# -- 案例 1：有受眾座標的一輪——10 列、指紋七維、7 主力＋3 探索、建議落在 1..10 -------------

class KnownAudienceRoundTest(_ImageRoundTestBase):
    def test_ten_rows_with_fingerprint_and_plan(self):
        audience = self._key_row("audience", "cold_unaware")
        brief_id = self._submit(coordinates={"audience": audience["label"]})

        workbench_jobs.PROVIDER = _ImageProvider(
            identity=_identity_reply(), image_task="stop_relate",
            subject_role="incidental", persuasion="none",
        )
        self._run_worker()

        brief = workbench_repo.get_brief(web.conn, self.org_id, self.brand_id, brief_id)
        self.assertEqual(brief["status"], "done")

        rows = self._outputs(brief_id)
        self.assertEqual(len(rows), 10)
        self.assertTrue(all(r["generation_round"] == 1 for r in rows))

        prompt_sent = workbench_jobs.PROVIDER.calls[-1]
        self.assertIn("陌生・不知有問題", prompt_sent)
        self.assertNotIn("cold_unaware", prompt_sent)
        self.assertIn("4:5", prompt_sent)

        for row in rows:
            body = row["body_json"]
            self.assertIn("品牌視覺規範：", body["text"])
            self.assertIn("風格規範：", body["text"])
            fp = body["fingerprint"]
            self.assertEqual(
                set(fp), {"image_task", "device", "layout", "look", "subject_role",
                          "persuasion", "slot"},
            )
            for dim in fp.values():
                self.assertIn("key", dim)
                self.assertIn("label", dim)
        plan = rows[0]["body_json"]["round"]["plan"]
        self.assertEqual(len(plan), 10)
        slots = [p["slot"] for p in plan]
        self.assertEqual(slots.count("exploit"), 7)
        self.assertEqual(slots.count("explore"), 3)
        recommended = rows[0]["body_json"]["round"]["recommended_index"]
        self.assertIn(recommended, range(1, 11))
        self.assertEqual(rows[0]["body_json"]["round"]["audience_key"], "cold_unaware")


# -- 案例 2：沒有受眾座標（或解不出任務表）——工作單列整張任務表、schema 要求 image_task ---

class UnknownAudienceRoundTest(_ImageRoundTestBase):
    def test_brand_made_key_treated_like_no_audience(self):
        # 種一筆會被「已知受眾」讀到的視覺學習——applicability_scope 的 audience 就是這輪
        # 座標快照裡那個未知值本身（`k_custom`），confidence／180 天內都合格。widening
        # 一旦把「未知受眾」也當已知受眾去讀學習，這筆就會被讀到，`learning_ids` 就不會是
        # 空的——證明見票的回報（monkeypatch `looks.visual_learnings`，只在記憶體裡驗證）。
        bi_repo.record_learning(
            web.conn, self.brand_id, actor=ACTOR,
            learning_text="soft_lifestyle 在 k_custom 這個受眾表現最好。",
            applicability_scope="visual；audience=k_custom；look=soft_lifestyle",
            confidence="likely", sample_size="n=40", source_track="visual",
        )
        brief_id = self._submit(coordinates={"audience": "k_custom"})
        workbench_jobs.PROVIDER = _ImageProvider(
            identity=_identity_reply(), image_task="believe_solution",
        )
        self._run_worker()

        prompt_sent = workbench_jobs.PROVIDER.calls[-1]
        self.assertIn("先從下表選一個，回在 image_task", prompt_sent)
        for key in visual.TASKS.values():
            self.assertIn(key["key"], prompt_sent)

        rows = self._outputs(brief_id)
        self.assertEqual(len(rows), 10)
        self.assertEqual(rows[0]["body_json"]["round"]["audience_key"], "k_custom")
        self.assertEqual(rows[0]["body_json"]["round"]["image_task"], "believe_solution")
        # 沒有受眾（或受眾解不出任務表）不讀視覺學習。
        self.assertEqual(rows[0]["body_json"]["round"]["learning_ids"], [])


# -- 案例 3：輪播——2 列，各自 5 張卡 ------------------------------------------------------

class CarouselRoundTest(_ImageRoundTestBase):
    def test_two_rows_five_cards_each(self):
        format_row = self._key_row("format", "carousel")
        brief_id = self._submit(coordinates={"format": format_row["label"]})
        workbench_jobs.PROVIDER = _ImageProvider(
            identity=_identity_reply(), image_task="believe_solution", shape="carousel",
        )
        self._run_worker()

        rows = self._outputs(brief_id)
        self.assertEqual(len(rows), 2)
        for row in rows:
            body = row["body_json"]
            self.assertEqual(len(body["cards"]), 5)
            self.assertIn("品牌視覺規範：", body["cards"][0]["text"])
        prompt_sent = workbench_jobs.PROVIDER.calls[-1]
        self.assertIn("1:1", prompt_sent)


# -- 案例 4：修正輪——item 3 的 look 錯了，被點名重問；換掉 subject_role 仍不合格停留 ❌ -----

class FixRoundTest(_ImageRoundTestBase):
    def test_wrong_look_triggers_one_fix_call(self):
        brief_id = self._submit()
        provider = _ImageProvider(identity=_identity_reply(), image_task="believe_solution")

        # 包一層：第一次正輪回覆把 item 3 的 look 故意寫錯（跟分配的不一樣），
        # 修正輪回覆把它換回分配的那一個。
        original_reply = provider._image_reply

        state = {"plan": None}

        def _broken_first_reply(text: str) -> dict:
            data = original_reply(text)
            plan = {int(n): look for n, look in _LOOK_LINE_RE.findall(text)}
            state["plan"] = plan
            correct_look = plan[3]
            broken_look = "dark_luxury" if correct_look != "dark_luxury" else "cinematic"
            data["items"][2]["look"] = broken_look
            fixed_item = dict(data["items"][2])
            fixed_item["look"] = correct_look
            provider._fix = {"replacements": [{"path": "items[3]", "value": fixed_item}]}
            return data

        provider._image_reply = _broken_first_reply
        workbench_jobs.PROVIDER = provider
        self._run_worker()

        image_calls = [
            c for c in provider.calls
            if "品牌視覺總監" not in c and "這些欄位沒有通過驗證" not in c
        ]
        self.assertEqual(len(image_calls), 1, "只問一次正輪")

        fix_calls = [c for c in provider.calls if "這些欄位沒有通過驗證，只重新回答這些" in c]
        self.assertEqual(len(fix_calls), 1)
        self.assertIn("- path: items[3]", fix_calls[0])
        self.assertIn(f"look 固定回 {state['plan'][3]}", fix_calls[0])

        rows = self._outputs(brief_id)
        self.assertEqual(len(rows), 10)
        item3 = rows[2]["body_json"]
        self.assertEqual(item3["fingerprint"]["look"]["key"], state["plan"][3])
        validation = item3["validation"]
        self.assertTrue(all(line.startswith("✅") for line in validation), validation)


# -- 案例 5：第二輪在同一個 knowledge_version——identity 只推導一次 -------------------------

class IdentityRunsOnceAcrossRoundsTest(_ImageRoundTestBase):
    def test_identity_task_ran_once_in_total(self):
        brief_id = self._submit()
        provider = _ImageProvider(identity=_identity_reply(), image_task="believe_solution")
        workbench_jobs.PROVIDER = provider
        self._run_worker()

        background_module.enqueue(
            "background.workbench_generate", org_id=self.org_id,
            lock=f"workbench:{brief_id}:image_prompt",
            brand_id=self.brand_id, brief_id=brief_id, part="image_prompt", count=None,
        )
        self._run_worker()

        identity_calls = [c for c in provider.calls if "品牌視覺總監" in c]
        self.assertEqual(len(identity_calls), 1)
        rows = self._outputs(brief_id)
        self.assertEqual(sorted({r["generation_round"] for r in rows}), [1, 2])


# -- 案例 6：確認過的 visual_base 品牌事實——brand_spec 那些列的風格規範是原文逐字 -----------

class BrandSpecTailTest(_ImageRoundTestBase):
    def test_brand_spec_look_uses_verbatim_spec_text(self):
        spec_text = (
            "手機直式實拍，未修圖，光線略暗但真實，畫面裡容許雜物與皺褶，不追求完美擺拍。"
        )
        bi_repo.create_brand_fact(
            web.conn, self.brand_id, actor=ACTOR, fact_type="visual_base", label="視覺基礎",
            value=spec_text, status="confirmed", confirmed_by=ACTOR,
        )
        brief_id = self._submit()
        workbench_jobs.PROVIDER = _ImageProvider(
            identity=_identity_reply(), image_task="believe_solution",
        )
        self._run_worker()

        rows = self._outputs(brief_id)
        spec_rows = [
            r for r in rows if r["body_json"]["fingerprint"]["look"]["key"] == "brand_spec"
        ]
        self.assertTrue(spec_rows, "brand_spec 是 fit_looks 第一個，分配一定至少用到一次")
        for row in spec_rows:
            self.assertIn(f"風格規範：{spec_text}", row["body_json"]["text"])


# -- 案例 7：`submit_pack`／`run_part` 不再要求 image_prompt 的張數 -------------------------

class NoImagePromptCountRequiredTest(_ImageRoundTestBase):
    def test_submit_pack_without_image_prompt_count_succeeds(self):
        pack = {
            "source_kind": "schedule_node", "source_ref": {"source_tree_task_id": "tree_1"},
            "name": "測試任務包", "summary": {"情境": "測試"},
            "sets": [{
                "name": "單元 1", "source_ref": {"node_key": "1"}, "coordinates": {},
                "style_key": "ugc", "required_outputs": {"image_prompt": 1},
                "request": {},
            }],
        }
        pack_id = workbench_repo.submit_pack(web.conn, self.org_id, self.brand_id, pack)
        self.assertIsNotNone(pack_id)
        rows = web.conn.execute(
            "SELECT request_json FROM workbench_brief WHERE org_id = %s AND brand_id = %s"
            " AND pack_id = %s", (self.org_id, self.brand_id, pack_id),
        ).fetchall()
        self.assertEqual(rows[0]["request_json"]["parts"], ["image_prompt"])

    def test_run_part_accepts_no_count_for_image_prompt(self):
        brief_id = self._submit()
        web.conn.execute("UPDATE workbench_brief SET status = 'done' WHERE id = %s", (brief_id,))
        web.conn.commit()
        workbench_repo.run_part(web.conn, self.org_id, self.brand_id, brief_id, "image_prompt")
        brief = workbench_repo.get_brief(web.conn, self.org_id, self.brand_id, brief_id)
        self.assertEqual(brief["status"], "queued")


# -- 工作單 golden 測試：純函式，不碰 DB。任何改寫／改包／改行都要讓這裡變紅 --------------

class WorksheetGoldenTest(unittest.TestCase):
    def test_single_audience_known_every_optional_line(self):
        text = workbench_prompts.image_worksheet(
            shape="single",
            reference_line="商品參考：顧問本人照片（有參考照）",
            identity_text="都會生活感，人物二十到三十五歲，配色暖米大地色，情緒放鬆自在。",
            plan=[("documentary", "exploit"), ("soft_lifestyle", "exploit")],
            coordinate_lines=[
                "- 受眾：陌生・知道問題（已經感覺到問題，還沒找答案）",
                "- 痛點：怕挑錯（買過後悔的經驗）",
            ],
            task_line=(
                "這張圖的任務：先建立信任——展示證明與細節"
                "（subject_role 只能 clear／hero；persuasion 只能 none／credential）"
            ),
            task_rows_lines=[],
            device_order=["contrast", "metaphor"],
            quotable_lines=["滿千折百", "前 100 名送小禮"],
            situation="秋冬回購檔期",
            key_messages="強調保固與快速到貨",
            free_text="多一點溫暖手寫感",
            prior_titles=["晨光儀式", "溫柔提醒"],
            learning_lines=["柔光生活在同受眾曾經勝出", "紀實自然光近期表現持平"],
            learning_omitted=1,
        )
        expected = (
            "## 工作單\n"
            "\n"
            "用途：4:5 直式單圖廣告，1080×1350（Meta 單圖廣告）\n"
            "\n"
            "商品參考：顧問本人照片（有參考照）\n"
            "品牌視覺規範：都會生活感，人物二十到三十五歲，配色暖米大地色，情緒放鬆自在。\n"
            "\n"
            "每則風格分配：\n"
            "- 第 1 則：documentary（紀實自然光）\n"
            "- 第 2 則：soft_lifestyle（柔光生活）\n"
            "\n"
            "這則廣告的座標：\n"
            "- 受眾：陌生・知道問題（已經感覺到問題，還沒找答案）\n"
            "- 痛點：怕挑錯（買過後悔的經驗）\n"
            "\n"
            "這張圖的任務：先建立信任——展示證明與細節"
            "（subject_role 只能 clear／hero；persuasion 只能 none／credential）\n"
            "\n"
            "這一輪手法清單順序（可任選，不必照順序）：contrast、metaphor\n"
            "\n"
            "可用字句（逐字，不得改）：滿千折百／前 100 名送小禮\n"
            "\n"
            "題材：秋冬回購檔期；強調保固與快速到貨\n"
            "自由指示：多一點溫暖手寫感\n"
            "上一輪的標題：晨光儀式、溫柔提醒\n"
            "\n"
            "已知的視覺學習：\n"
            "- 柔光生活在同受眾曾經勝出\n"
            "- 紀實自然光近期表現持平\n"
            "另有 1 條沒列出"
        )
        self.assertEqual(text, expected)

    def test_carousel_header_and_slot_lines(self):
        text = workbench_prompts.image_worksheet(
            shape="carousel",
            reference_line="商品參考：沒有參考照",
            identity_text="識別文字",
            plan=[("documentary", "exploit"), ("dark_luxury", "explore")],
            coordinate_lines=[],
            task_line=(
                "這張圖的任務：先建立信任——展示證明與細節"
                "（subject_role 只能 clear；persuasion 只能 none）"
            ),
            task_rows_lines=[],
            device_order=["contrast"],
            quotable_lines=[],
            situation="",
            key_messages="",
            free_text=None,
            prior_titles=[],
            learning_lines=[],
            learning_omitted=0,
        )
        expected = (
            "## 工作單\n"
            "\n"
            "用途：1:1 輪播卡片，1080×1080（Meta 輪播廣告）\n"
            "\n"
            "商品參考：沒有參考照\n"
            "品牌視覺規範：識別文字\n"
            "\n"
            "每則風格分配：\n"
            "- 第 1 組：documentary（紀實自然光）\n"
            "- 第 2 組：dark_luxury（暗調精品）\n"
            "\n"
            "這張圖的任務：先建立信任——展示證明與細節"
            "（subject_role 只能 clear；persuasion 只能 none）\n"
            "\n"
            "這一輪手法清單順序（可任選，不必照順序）：contrast\n"
            "\n"
            "可用字句（逐字，不得改）：（無）\n"
            "\n"
            "已知的視覺學習：（無）"
        )
        self.assertEqual(text, expected)

    def test_no_audience_task_rows_no_situation_no_learnings(self):
        text = workbench_prompts.image_worksheet(
            shape="single",
            reference_line="商品參考：沒有參考照",
            identity_text="識別文字",
            plan=[("documentary", "exploit")],
            coordinate_lines=[],
            task_line="這張圖的任務：先從下表選一個，回在 image_task",
            task_rows_lines=[
                "- believe_solution：先建立信任——展示證明與細節"
                "（subject_role 只能 clear／hero；persuasion 只能 none／credential）",
                "- stop_relate：先讓對方覺得被理解——同理這則痛點"
                "（subject_role 只能 incidental／clear；persuasion 只能 none）",
            ],
            device_order=["contrast"],
            quotable_lines=[],
            situation="",
            key_messages="",
            free_text=None,
            prior_titles=[],
            learning_lines=[],
            learning_omitted=0,
        )
        expected = (
            "## 工作單\n"
            "\n"
            "用途：4:5 直式單圖廣告，1080×1350（Meta 單圖廣告）\n"
            "\n"
            "商品參考：沒有參考照\n"
            "品牌視覺規範：識別文字\n"
            "\n"
            "每則風格分配：\n"
            "- 第 1 則：documentary（紀實自然光）\n"
            "\n"
            "這張圖的任務：先從下表選一個，回在 image_task\n"
            "- believe_solution：先建立信任——展示證明與細節"
            "（subject_role 只能 clear／hero；persuasion 只能 none／credential）\n"
            "- stop_relate：先讓對方覺得被理解——同理這則痛點"
            "（subject_role 只能 incidental／clear；persuasion 只能 none）\n"
            "\n"
            "這一輪手法清單順序（可任選，不必照順序）：contrast\n"
            "\n"
            "可用字句（逐字，不得改）：（無）\n"
            "\n"
            "已知的視覺學習：（無）"
        )
        self.assertEqual(text, expected)

    def test_subject_group_only_situation_no_separator(self):
        text = workbench_prompts.image_worksheet(
            shape="single",
            reference_line="商品參考：沒有參考照",
            identity_text="識別文字",
            plan=[("documentary", "exploit")],
            coordinate_lines=[],
            task_line="這張圖的任務：先建立信任——展示證明與細節（subject_role 只能 clear）",
            task_rows_lines=[],
            device_order=["contrast"],
            quotable_lines=[],
            situation="秋冬回購檔期",
            key_messages="",
            free_text=None,
            prior_titles=[],
            learning_lines=[],
            learning_omitted=0,
        )
        self.assertIn("題材：秋冬回購檔期\n", text)
        self.assertNotIn("題材：秋冬回購檔期；", text)


# -- P03／K1／K2：座標行帶 situation、痛點維度沒被漏掉 -------------------------------------

class CoordinateLinesTest(_ImageRoundTestBase):
    def test_situation_and_pain_dimension_present(self):
        audience = self._key_row("audience", "cold_unaware")
        pain = self._key_row("pain", "uncertainty")
        brief_id = self._submit(coordinates={"audience": audience["key"], "pain": pain["key"]})
        provider = _ImageProvider(identity=_identity_reply(), image_task="stop_relate")
        workbench_jobs.PROVIDER = provider
        self._run_worker()

        prompt_sent = provider.calls[-1]
        audience_situation = (audience["attributes"] or {}).get("situation")
        pain_situation = (pain["attributes"] or {}).get("situation")
        self.assertIn(f"- 受眾：{audience['label']}（{audience_situation}）", prompt_sent)
        self.assertIn(f"- 痛點：{pain['label']}（{pain_situation}）", prompt_sent)
        self._outputs(brief_id)  # sanity: round wrote fine


# -- T1／T2：任務行帶 how，persuasion 只列這個誘因／證明真的能導出的那幾個 -------------------

class TaskLineWordingTest(_ImageRoundTestBase):
    def test_known_audience_task_line_and_persuasion_filtered(self):
        bi_repo.set_brand_switches(
            web.conn, self.brand_id, market_region=None, conversion_goal="booking", actor=ACTOR,
        )
        audience = self._key_row("audience", "warm_engaged")
        offer = self._key_row("offer", "discount")
        proof = self._key_row("proof", "none")
        self._submit(coordinates={
            "audience": audience["key"], "offer": offer["key"], "proof": proof["key"],
        })
        provider = _ImageProvider(
            identity=_identity_reply(), image_task="convert", subject_role="clear",
            persuasion="none",
        )
        workbench_jobs.PROVIDER = provider
        self._run_worker()

        prompt_sent = provider.calls[-1]
        self.assertIn(
            "這張圖的任務：讓猶豫的人預約——主角主視覺、誘因與截止、打消疑慮"
            "（subject_role 只能 clear／hero；"
            "persuasion 只能 none／offer_headline／price_breakdown）",
            prompt_sent,
        )


# -- T3／U3b／R9b：沒有受眾時整張任務表照新措辭，conversion_goal 照樣代進 {close} ------------

class UnknownAudienceTaskTableTest(_ImageRoundTestBase):
    def test_task_rows_full_wording_and_conversion_goal(self):
        bi_repo.set_brand_switches(
            web.conn, self.brand_id, market_region=None, conversion_goal="booking", actor=ACTOR,
        )
        brief_id = self._submit(coordinates={"audience": "舊受眾・已刪除"})
        provider = _ImageProvider(identity=_identity_reply(), image_task="convert")
        workbench_jobs.PROVIDER = provider
        self._run_worker()

        prompt_sent = provider.calls[-1]
        expected_rows = visual.all_task_rows("booking", None, None)
        for key, row in expected_rows.items():
            expected_line = (
                f"- {key}：{row['label']}——{row['how']}"
                f"（subject_role 只能 {'／'.join(row['subject_role'])}"
                f"；persuasion 只能 {'／'.join(row['persuasion'])}）"
            )
            self.assertIn(expected_line, prompt_sent)
        self.assertIn("讓猶豫的人預約", prompt_sent)

        rows = self._outputs(brief_id)
        self.assertEqual(rows[0]["body_json"]["round"]["audience_key"], "舊受眾・已刪除")
        self.assertEqual(
            rows[0]["body_json"]["fingerprint"]["image_task"],
            {"key": "convert", "label": expected_rows["convert"]["label"]},
        )


# -- M31／M39：offer／proof 真的能導出的誘因以外，一律 ❌，不因為受眾已知／未知而放寬 ---------

class PersuasionMismatchTest(_ImageRoundTestBase):
    def test_known_audience_persuasion_not_widened(self):
        audience = self._key_row("audience", "cold_problem_aware")
        offer = self._key_row("offer", "discount")
        proof = self._key_row("proof", "none")
        brief_id = self._submit(coordinates={
            "audience": audience["key"], "offer": offer["key"], "proof": proof["key"],
        })
        provider = _ImageProvider(
            identity=_identity_reply(), image_task="believe_solution",
            subject_role="clear", persuasion="testimonial",
        )
        workbench_jobs.PROVIDER = provider
        self._run_worker()
        rows = self._outputs(brief_id)
        validation = rows[0]["body_json"]["validation"]
        self.assertTrue(
            any(line.startswith("❌") and ".persuasion" in line for line in validation), validation,
        )

    def test_no_audience_persuasion_not_widened(self):
        brief_id = self._submit(coordinates={"audience": "k_unknown_persuasion"})
        provider = _ImageProvider(
            identity=_identity_reply(), image_task="believe_solution",
            subject_role="clear", persuasion="offer_headline",
        )
        workbench_jobs.PROVIDER = provider
        self._run_worker()
        rows = self._outputs(brief_id)
        validation = rows[0]["body_json"]["validation"]
        self.assertTrue(
            any(line.startswith("❌") and ".persuasion" in line for line in validation), validation,
        )


# -- M28／C4-C7：分類術語才進 leak_terms，一個都不能少也不能多 ------------------------------

class LeakTermsContextTest(_ImageRoundTestBase):
    def test_leak_terms_include_audience_angle_hook_and_task(self):
        audience = self._key_row("audience", "cold_unaware")
        angle = self._key_row("angle", "scarcity_marketing")
        hook = self._key_row("hook", "pain_question")
        proof_none = self._key_row("proof", "none")
        brand = bi_repo.get_brand(web.conn, self.brand_id)
        brief = {"coordinates_snapshot_json": {
            "audience": audience["key"], "angle": angle["key"], "hook": hook["key"],
            "proof": proof_none["key"],
        }}
        ctx = workbench_jobs._image_task_context(web.conn, self.org_id, self.brand_id, brand, brief)
        expected = [
            audience["label"], angle["label"], hook["label"], proof_none["label"],
            ctx["task_row"]["label"],
        ]
        self.assertEqual(ctx["leak_terms"], expected)

    def test_proof_label_not_leak_term_when_not_none(self):
        audience = self._key_row("audience", "cold_unaware")
        proof = self._key_row("proof", "customer_review")
        brand = bi_repo.get_brand(web.conn, self.brand_id)
        brief = {"coordinates_snapshot_json": {"audience": audience["key"], "proof": proof["key"]}}
        ctx = workbench_jobs._image_task_context(web.conn, self.org_id, self.brand_id, brand, brief)
        self.assertNotIn(proof["label"], ctx["leak_terms"])


class LeakTermRoundTest(_ImageRoundTestBase):
    def test_leak_term_in_prompt_marked_bad(self):
        audience = self._key_row("audience", "cold_unaware")
        brief_id = self._submit(coordinates={"audience": audience["key"]})
        provider = _ImageProvider(
            identity=_identity_reply(), image_task="stop_relate",
            subject_role="incidental", persuasion="none",
        )
        original_reply = provider._image_reply

        def _leaky_reply(text: str) -> dict:
            data = original_reply(text)
            data["items"][0]["prompt"] += "畫面角落寫著「陌生・不知有問題」的小卡。"
            return data

        provider._image_reply = _leaky_reply
        workbench_jobs.PROVIDER = provider
        self._run_worker()

        rows = self._outputs(brief_id)
        validation = rows[0]["body_json"]["validation"]
        self.assertTrue(
            any(
                line.startswith("❌") and "items[1].prompt_leak" in line for line in validation
            ),
            validation,
        )


# -- Q1／Q2／M27：可用字句來源——促銷備註、重點訊息、品牌上下文各自獨立算進可引用文字 ---------

class QuotableTextSourcesTest(_ImageRoundTestBase):
    def _run_with_quoted_number(self, brief_id: str, image_task="believe_solution") -> list:
        provider = _ImageProvider(identity=_identity_reply(), image_task=image_task)
        original_reply = provider._image_reply

        def _quoting_reply(text: str) -> dict:
            data = original_reply(text)
            data["items"][0]["prompt"] += "海報角落印著「月銷500件」字樣。"
            return data

        provider._image_reply = _quoting_reply
        workbench_jobs.PROVIDER = provider
        self._run_worker()
        rows = self._outputs(brief_id)
        return rows[0]["body_json"]["validation"]

    def test_promotion_note_number_is_quotable(self):
        brief_id = self._submit(
            request={"parts": ["image_prompt"], "promotion_note": "限量200組"},
        )
        provider = _ImageProvider(identity=_identity_reply(), image_task="believe_solution")
        original_reply = provider._image_reply

        def _quoting_reply(text: str) -> dict:
            data = original_reply(text)
            data["items"][0]["prompt"] += "海報角落印著「200組」字樣。"
            return data

        provider._image_reply = _quoting_reply
        workbench_jobs.PROVIDER = provider
        self._run_worker()
        rows = self._outputs(brief_id)
        validation = rows[0]["body_json"]["validation"]
        self.assertFalse(
            any("prompt_numbers" in line and line.startswith("❌") for line in validation),
            validation,
        )

    def test_pack_key_message_number_is_quotable(self):
        pack_id = workbench_repo.create_pack(web.conn, self.org_id, self.brand_id, {
            "source_kind": "free_job", "summary": {"情境": "秋季檔期", "重點訊息": "月銷500件"},
        })
        brief_id = workbench_repo.submit_brief(
            web.conn, self.org_id, self.brand_id,
            {"source_kind": "manual", "source_ref": {}, "product_id": self.product["id"],
             "coordinates": {}, "style_key": "ugc", "request": {"parts": ["image_prompt"]}},
            pack_id=pack_id,
        )
        validation = self._run_with_quoted_number(brief_id)
        self.assertFalse(
            any("prompt_numbers" in line and line.startswith("❌") for line in validation),
            validation,
        )

    def test_brand_context_number_is_quotable(self):
        bi_repo.create_brand_fact(
            web.conn, self.brand_id, actor=ACTOR, fact_type="positioning", label="定位",
            value="月銷500件", status="confirmed", confirmed_by=ACTOR,
        )
        brief_id = self._submit(request={
            "parts": ["image_prompt"], "product_ids": [self.product["id"]],
            "use_brand_knowledge": True,
        })
        validation = self._run_with_quoted_number(brief_id)
        self.assertFalse(
            any("prompt_numbers" in line and line.startswith("❌") for line in validation),
            validation,
        )


# -- Q3／Q4／Q5／RP1：題材、自由指示、上一輪標題都要流進第二輪的工作單 -----------------------

class WorksheetInputsRoundTest(_ImageRoundTestBase):
    def test_situation_free_text_and_prior_titles_flow_into_round_two(self):
        pack_id = workbench_repo.create_pack(web.conn, self.org_id, self.brand_id, {
            "source_kind": "free_job",
            "summary": {"情境": "秋季回購檔期", "重點訊息": "老客戶回購禮"},
        })
        brief_id = workbench_repo.submit_brief(
            web.conn, self.org_id, self.brand_id,
            {"source_kind": "manual", "source_ref": {}, "product_id": self.product["id"],
             "coordinates": {}, "style_key": "ugc",
             "request": {"parts": ["image_prompt"], "free_text": "想要溫暖手寫感"}},
            pack_id=pack_id,
        )
        provider = _ImageProvider(identity=_identity_reply(), image_task="believe_solution")
        workbench_jobs.PROVIDER = provider
        self._run_worker()

        background_module.enqueue(
            "background.workbench_generate", org_id=self.org_id,
            lock=f"workbench:{brief_id}:image_prompt:round2",
            brand_id=self.brand_id, brief_id=brief_id, part="image_prompt", count=None,
        )
        self._run_worker()

        prompt_sent = provider.calls[-1]
        self.assertIn("題材：秋季回購檔期；老客戶回購禮", prompt_sent)
        self.assertIn("自由指示：想要溫暖手寫感", prompt_sent)
        self.assertIn("上一輪的標題：", prompt_sent)
        self.assertIn("點子1", prompt_sent)


# -- A1／A2／A3：prompt 一定以部門檔開頭、以品牌上下文收尾，方法論不再夾帶創意矩陣 -----------

class PromptAssemblyTest(_ImageRoundTestBase):
    def test_prompt_starts_with_department_file_and_ends_with_brand_context(self):
        bi_repo.create_brand_fact(
            web.conn, self.brand_id, actor=ACTOR, fact_type="positioning", label="定位",
            value="專攻辦公室午後咖啡儀式感。", status="confirmed", confirmed_by=ACTOR,
        )
        brief_id = self._submit(request={
            "parts": ["image_prompt"], "product_ids": [self.product["id"]],
            "use_brand_knowledge": True,
        })
        provider = _ImageProvider(identity=_identity_reply(), image_task="believe_solution")
        workbench_jobs.PROVIDER = provider
        self._run_worker()

        prompt_sent = provider.calls[-1]
        department_text = (workbench_jobs.DEPARTMENTS_DIR / "image_prompt.md").read_text(
            encoding="utf-8"
        )
        self.assertTrue(prompt_sent.startswith(department_text))
        self.assertIn("## 工作單", prompt_sent)
        self.assertNotIn("# 創意矩陣", prompt_sent)

        brand_context, _ids, _v = workbench_jobs._compile_brand_context(
            web.conn, self.brand_id, [self.product["id"]],
        )
        self.assertTrue(brand_context)
        self.assertTrue(prompt_sent.endswith(brand_context))
        self._outputs(brief_id)


# -- E2／E3：程式分配吃得到 identity 的排除與適配順序 ---------------------------------------

class AllocationInputsTest(_ImageRoundTestBase):
    def test_excluded_look_never_in_plan(self):
        brief_id = self._submit()
        fake_identity = {
            "id": "wvi_fake", "identity_text": "識別文字",
            "fit_looks": ["soft_lifestyle", "documentary", "clean_bright"],
            "excluded_looks": [{"look": "phone_raw", "fact": "顧客都愛正式感"}],
            "brand_spec_text": None,
        }
        provider = _ImageProvider(identity=_identity_reply(), image_task="believe_solution")
        workbench_jobs.PROVIDER = provider
        with mock.patch.object(
            workbench_jobs.identity_mod, "ensure_identity", return_value=fake_identity,
        ):
            self._run_worker()
        rows = self._outputs(brief_id)
        plan = rows[0]["body_json"]["round"]["plan"]
        self.assertNotIn("phone_raw", [p["look"] for p in plan])

    def test_fit_order_used_for_exploit_looks(self):
        brief_id = self._submit()
        fake_identity = {
            "id": "wvi_fake", "identity_text": "識別文字",
            "fit_looks": ["dark_luxury", "cinematic", "bold_graphic"],
            "excluded_looks": [], "brand_spec_text": None,
        }
        provider = _ImageProvider(identity=_identity_reply(), image_task="believe_solution")
        workbench_jobs.PROVIDER = provider
        with mock.patch.object(
            workbench_jobs.identity_mod, "ensure_identity", return_value=fake_identity,
        ):
            self._run_worker()
        rows = self._outputs(brief_id)
        round_dict = rows[0]["body_json"]["round"]
        self.assertEqual(
            round_dict["look_order"]["exploit"], ["dark_luxury", "cinematic", "bold_graphic"],
        )


# -- L1-L3／W1／M16：視覺學習餵進工作單、只有真的勝出的風格才會被排進主力 --------------------

class LearningsTest(_ImageRoundTestBase):
    def test_learnings_seed_lines_and_winner_look(self):
        audience = self._key_row("audience", "cold_unaware")
        dims = [
            ("look", "soft_lifestyle"), ("device", "contrast"), ("layout", "candid_scene"),
            ("subject_role", "clear"), ("persuasion", "none"), ("hook", "pain_question"),
        ]
        for i, (dim, val) in enumerate(dims):
            bi_repo.record_learning(
                web.conn, self.brand_id, actor=ACTOR,
                learning_text=f"學習{i}：{dim}={val} 的表現。",
                applicability_scope=f"visual；audience=cold_unaware；{dim}={val}",
                confidence="likely", sample_size="n=40", source_track="visual",
            )
        brief_id = self._submit(coordinates={"audience": audience["key"]})
        provider = _ImageProvider(identity=_identity_reply(), image_task="stop_relate")
        workbench_jobs.PROVIDER = provider
        self._run_worker()

        prompt_sent = provider.calls[-1]
        self.assertIn("已知的視覺學習：", prompt_sent)
        self.assertIn("另有 1 條沒列出", prompt_sent)
        self.assertEqual(prompt_sent.count("- 學習"), 5)

        rows = self._outputs(brief_id)
        round_dict = rows[0]["body_json"]["round"]
        self.assertEqual(round_dict["look_order"]["exploit"], ["soft_lifestyle"])
        self.assertTrue(round_dict["learning_ids"])


# -- H1／H2：同一個受眾第二輪的探索格要跟第一輪不一樣（history 真的有讀到） -----------------

class HistoryAcrossRoundsTest(_ImageRoundTestBase):
    def test_second_round_explore_differs_from_first(self):
        audience = self._key_row("audience", "cold_unaware")
        brief_id = self._submit(coordinates={"audience": audience["key"]})
        provider = _ImageProvider(identity=_identity_reply(), image_task="stop_relate")
        workbench_jobs.PROVIDER = provider
        self._run_worker()
        rows1 = self._outputs(brief_id)
        explore1 = rows1[0]["body_json"]["round"]["look_order"]["explore"]

        background_module.enqueue(
            "background.workbench_generate", org_id=self.org_id,
            lock=f"workbench:{brief_id}:image_prompt:round2",
            brand_id=self.brand_id, brief_id=brief_id, part="image_prompt", count=None,
        )
        self._run_worker()
        rows = web.conn.execute(
            "SELECT * FROM workbench_output WHERE brief_id = %s AND part = 'image_prompt'"
            " AND generation_round = 2 ORDER BY version_index", (brief_id,),
        ).fetchall()
        rows2 = [dict(r) for r in rows]
        explore2 = rows2[0]["body_json"]["round"]["look_order"]["explore"]
        self.assertNotEqual(explore1, explore2)


# -- M07／M08／R11／M15：程式分配跟裝置洗牌真的用同一個 RNG，round.plan／look_order 沒被動手腳 --

class RNGReplayTest(_ImageRoundTestBase):
    def test_plan_and_device_order_match_seeded_rng(self):
        brief_id = self._submit()
        seed = 11
        orig_rng = workbench_jobs.RNG
        workbench_jobs.RNG = random.Random(seed)
        try:
            provider = _ImageProvider(identity=_identity_reply(), image_task="believe_solution")
            workbench_jobs.PROVIDER = provider
            self._run_worker()
        finally:
            workbench_jobs.RNG = orig_rng

        r = random.Random(seed)
        alloc = looks_mod.allocate(
            10, fit_looks=["soft_lifestyle", "documentary", "clean_bright"],
            excluded=[], winners=[], history={}, rng=r,
        )
        devices = list(visual.DEVICES)
        r.shuffle(devices)

        rows = self._outputs(brief_id)
        plan = rows[0]["body_json"]["round"]["plan"]
        self.assertEqual([(p["look"], p["slot"]) for p in plan], alloc["plan"])
        prompt_sent = provider.calls[-1]
        self.assertIn("、".join(devices), prompt_sent)


# -- Row contract: 每一列的九個鍵、指紋、round 字典都逐項核對 -------------------------------

class RowContractTest(_ImageRoundTestBase):
    def test_full_body_and_round_contract(self):
        audience = self._key_row("audience", "cold_unaware")
        format_row = self._key_row("format", "single_image")
        brief_id = self._submit(coordinates={
            "audience": audience["key"], "format": format_row["key"],
        })
        provider = _ImageProvider(
            identity=_identity_reply(), image_task="stop_relate",
            subject_role="incidental", persuasion="none",
        )
        workbench_jobs.PROVIDER = provider
        self._run_worker()

        rows = self._outputs(brief_id)
        self.assertEqual(len(rows), 10)

        identity_row = web.conn.execute(
            "SELECT * FROM workbench_visual_identity WHERE brand_id = %s", (self.brand_id,),
        ).fetchone()
        task_row = web.conn.execute(
            "SELECT id FROM llm_task WHERE brand_id = %s AND task_type = 'workbench_image_prompt'"
            " ORDER BY started_at DESC LIMIT 1", (self.brand_id,),
        ).fetchone()

        round_dict = rows[0]["body_json"]["round"]
        plan = round_dict["plan"]
        for i, row in enumerate(rows, start=1):
            body = row["body_json"]
            self.assertEqual(
                set(body),
                {"title", "headline", "prompt", "text", "fingerprint", "cards", "round",
                 "validation", "warnings"},
            )
            look, slot = plan[i - 1]["look"], plan[i - 1]["slot"]
            expected_item = _item(i, look, subject_role="incidental", persuasion="none")
            self.assertEqual(body["title"], expected_item["title"])
            self.assertEqual(body["headline"], expected_item["headline"])
            self.assertEqual(body["prompt"], expected_item["prompt"])
            expected_tail = (
                f"品牌視覺規範：{identity_row['identity_text']}\n"
                f"風格規範：{looks_mod.look_texture(look, None)}"
            )
            self.assertEqual(body["text"], f"{expected_item['prompt']}\n\n{expected_tail}")
            self.assertIsNone(body["cards"])
            self.assertEqual(body["warnings"], ["w1"])
            fp = body["fingerprint"]
            self.assertEqual(fp["look"], {"key": look, "label": looks_mod.look_label(look)})
            self.assertEqual(fp["slot"], {"key": slot, "label": visual.SLOTS[slot]})
            self.assertEqual(
                fp["device"],
                {"key": expected_item["device"], "label": visual.DEVICES[expected_item["device"]]},
            )
            self.assertEqual(
                fp["layout"],
                {"key": expected_item["layout"], "label": visual.LAYOUTS[expected_item["layout"]]},
            )
            self.assertEqual(fp["subject_role"], {"key": "incidental", "label": "順手帶到"})
            self.assertEqual(fp["persuasion"], {"key": "none", "label": "無"})
            self.assertEqual(
                fp["image_task"], {"key": "stop_relate", "label": "讓人停下來、有共鳴"},
            )
            self.assertEqual(row["llm_task_id"], task_row["id"])

        self.assertEqual(round_dict["format"], "single_image")
        self.assertEqual(round_dict["identity_id"], identity_row["id"])
        self.assertEqual(round_dict["identity_text"], identity_row["identity_text"])
        exploit_expected = {p["look"] for p in round_dict["plan"] if p["slot"] == "exploit"}
        explore_expected = {p["look"] for p in round_dict["plan"] if p["slot"] == "explore"}
        self.assertEqual(set(round_dict["look_order"]["exploit"]), exploit_expected)
        self.assertEqual(set(round_dict["look_order"]["explore"]), explore_expected)
        self.assertFalse(exploit_expected & explore_expected)
        recommended_slot = round_dict["plan"][round_dict["recommended_index"] - 1]["slot"]
        self.assertEqual(round_dict["recommended_slot"], recommended_slot)


# -- N1／M24／M25／R15：輪播兩組不能靠洗牌矇混、text 是兩張卡串起來、headline 拿第一卡 -------

class CarouselExtraTest(_ImageRoundTestBase):
    def test_plan_has_two_deterministic_entries(self):
        format_row = self._key_row("format", "carousel")
        brief_id = self._submit(coordinates={"format": format_row["key"]})
        workbench_jobs.PROVIDER = _ImageProvider(
            identity=_identity_reply(), image_task="believe_solution", shape="carousel",
        )
        self._run_worker()
        rows = self._outputs(brief_id)
        plan = rows[0]["body_json"]["round"]["plan"]
        self.assertEqual(len(plan), 2)
        self.assertEqual([p["look"] for p in plan], ["soft_lifestyle", "phone_raw"])
        self.assertEqual(rows[0]["body_json"]["fingerprint"]["look"]["key"], "soft_lifestyle")
        self.assertEqual(rows[1]["body_json"]["fingerprint"]["look"]["key"], "phone_raw")

    def test_concept_text_is_join_of_cards_and_headline_is_first_card(self):
        format_row = self._key_row("format", "carousel")
        brief_id = self._submit(coordinates={"format": format_row["key"]})
        workbench_jobs.PROVIDER = _ImageProvider(
            identity=_identity_reply(), image_task="believe_solution", shape="carousel",
        )
        self._run_worker()
        rows = self._outputs(brief_id)
        body = rows[0]["body_json"]
        self.assertEqual(body["text"], "\n\n".join(c["text"] for c in body["cards"]))
        self.assertEqual(body["headline"], body["cards"][0]["headline"])
        self.assertNotEqual(body["headline"], body["cards"][-1]["headline"])


# -- M04-M06／RC1：建議格考慮歷史比例，不是永遠第 1 格也不是永遠主力 -----------------------

class RecommendationIndexTest(_ImageRoundTestBase):
    def test_recommended_index_matches_first_exploit_slot(self):
        found_seed, expected_index = None, None
        for candidate in range(1, 50):
            r = random.Random(candidate)
            alloc = looks_mod.allocate(
                10, fit_looks=["soft_lifestyle", "documentary", "clean_bright"],
                excluded=[], winners=[], history={}, rng=r,
            )
            idx = next(i + 1 for i, (_look, slot) in enumerate(alloc["plan"]) if slot == "exploit")
            if idx != 1:
                found_seed, expected_index = candidate, idx
                break
        self.assertIsNotNone(found_seed, "no seed found with first-exploit index != 1")

        brief_id = self._submit()
        orig_rng = workbench_jobs.RNG
        workbench_jobs.RNG = random.Random(found_seed)
        try:
            provider = _ImageProvider(identity=_identity_reply(), image_task="believe_solution")
            workbench_jobs.PROVIDER = provider
            self._run_worker()
        finally:
            workbench_jobs.RNG = orig_rng

        rows = self._outputs(brief_id)
        self.assertEqual(rows[0]["body_json"]["round"]["recommended_index"], expected_index)


class RecommendationHistoryTest(_ImageRoundTestBase):
    def test_fourth_round_recommends_explore_after_three_exploit_rounds(self):
        provider = _ImageProvider(identity=_identity_reply(), image_task="believe_solution")
        workbench_jobs.PROVIDER = provider
        recommended_slots = []
        for _ in range(4):
            brief_id = self._submit()
            self._run_worker()
            rows = self._outputs(brief_id)
            recommended_slots.append(rows[0]["body_json"]["round"]["recommended_slot"])
        self.assertEqual(recommended_slots[:3], ["exploit", "exploit", "exploit"])
        self.assertEqual(recommended_slots[3], "explore")


# -- M32／RF4：賣法商品讀母產品的參考照、標題缺了退到賣法本身的名字 -------------------------

class ReferenceLineRunTest(_ImageRoundTestBase):
    def test_sell_way_product_reads_mother_photo(self):
        mother = bi_repo.create_product(
            web.conn, self.brand_id, name="晨光咖啡豆母產品", actor=ACTOR,
        )
        sell_way = bi_repo.create_product(
            web.conn, self.brand_id, name="晨光咖啡豆．訂閱組合", actor=ACTOR,
            parent_id=mother["id"],
        )
        bi_repo.create_official_asset(
            web.conn, self.brand_id, actor=ACTOR, asset_kind="product_photo",
            storage_key="k1", product_id=mother["id"], title=None,
        )
        web.conn.commit()
        self._submit(product_id=sell_way["id"])
        workbench_jobs.PROVIDER = _ImageProvider(
            identity=_identity_reply(), image_task="believe_solution",
        )
        self._run_worker()
        prompt_sent = workbench_jobs.PROVIDER.calls[-1]
        self.assertIn(f"商品參考：{sell_way['name']}（有參考照）", prompt_sent)


# -- V1：video_script 沒帶張數還是要炸 -------------------------------------------------------

class VideoScriptCountRequiredTest(_ImageRoundTestBase):
    def test_video_script_without_count_raises(self):
        pack_id = workbench_repo.create_pack(
            web.conn, self.org_id, self.brand_id, {"source_kind": "free_job"},
        )
        with self.assertRaises(ValueError):
            workbench_repo.submit_brief(
                web.conn, self.org_id, self.brand_id,
                {"source_kind": "manual", "source_ref": {}, "product_id": self.product["id"],
                 "coordinates": {}, "style_key": "ugc", "request": {"parts": ["video_script"]}},
                pack_id=pack_id,
            )


# -- M22／M23／SC1-SC6：schema 的 enum／上下限真的送出去，且真的帶了 tools ------------------

class SchemaTest(_ImageRoundTestBase):
    def test_single_known_audience_schema_enums_and_bounds(self):
        audience = self._key_row("audience", "cold_unaware")
        brief_id = self._submit(coordinates={"audience": audience["key"]})
        provider = _ImageProvider(
            identity=_identity_reply(), image_task="stop_relate",
            subject_role="incidental", persuasion="none",
        )
        workbench_jobs.PROVIDER = provider
        self._run_worker()
        self._outputs(brief_id)

        tools = provider.tool_calls[-1]
        self.assertIsNotNone(tools)
        schema = tools[0]
        self.assertNotIn("image_task", schema["input_schema"]["required"])
        item_props = schema["input_schema"]["properties"]["items"]["items"]["properties"]
        self.assertEqual(item_props["subject_role"]["enum"], ["absent", "incidental"])
        self.assertEqual(item_props["persuasion"]["enum"], ["none"])
        self.assertIn("enum", item_props["look"])
        self.assertEqual(item_props["headline"]["minItems"], 1)
        self.assertEqual(item_props["headline"]["maxItems"], 2)
        self.assertEqual(schema["input_schema"]["properties"]["items"]["minItems"], 10)
        self.assertEqual(schema["input_schema"]["properties"]["items"]["maxItems"], 10)

    def test_no_audience_schema_requires_image_task(self):
        brief_id = self._submit(coordinates={"audience": "k_custom"})
        provider = _ImageProvider(identity=_identity_reply(), image_task="believe_solution")
        workbench_jobs.PROVIDER = provider
        self._run_worker()
        self._outputs(brief_id)

        tools = provider.tool_calls[-1]
        schema = tools[0]
        self.assertIn("image_task", schema["input_schema"]["required"])
        self.assertEqual(
            set(schema["input_schema"]["properties"]["image_task"]["enum"]),
            {row["key"] for row in visual.TASKS.values()},
        )

    def test_carousel_schema_cards_bounded_and_tools_sent(self):
        format_row = self._key_row("format", "carousel")
        brief_id = self._submit(coordinates={"format": format_row["key"]})
        provider = _ImageProvider(
            identity=_identity_reply(), image_task="believe_solution", shape="carousel",
        )
        workbench_jobs.PROVIDER = provider
        self._run_worker()
        self._outputs(brief_id)

        tools = provider.tool_calls[-1]
        self.assertIsNotNone(tools)
        schema = tools[0]
        concept_props = schema["input_schema"]["properties"]["concepts"]["items"]["properties"]
        self.assertEqual(concept_props["cards"]["minItems"], 5)
        self.assertEqual(concept_props["cards"]["maxItems"], 5)


# -- C3／M02／X2／X4：整輪裁切先於檢查、重問失敗的欄位仍然被真正核對、round-level 不重問 ------

class FixRoundExtraTest(_ImageRoundTestBase):
    def test_eleven_item_reply_trims_to_ten(self):
        brief_id = self._submit()
        provider = _ImageProvider(identity=_identity_reply(), image_task="believe_solution")
        original_reply = provider._image_reply

        def _eleven_items(text: str) -> dict:
            data = original_reply(text)
            data["items"].append(dict(data["items"][0]))
            return data

        provider._image_reply = _eleven_items
        workbench_jobs.PROVIDER = provider
        self._run_worker()

        rows = self._outputs(brief_id)
        self.assertEqual(len(rows), 10)
        validation = rows[0]["body_json"]["validation"]
        self.assertFalse(any("items[11]" in line for line in validation))
        fix_calls = [c for c in provider.calls if "這些欄位沒有通過驗證，只重新回答這些" in c]
        self.assertEqual(
            len(fix_calls), 0,
            "the 11th (duplicate, valid) item must be trimmed before the first check runs, "
            "so it never triggers a fix call",
        )

    def test_recheck_still_flags_uncorrected_field(self):
        brief_id = self._submit()
        provider = _ImageProvider(identity=_identity_reply(), image_task="believe_solution")
        original_reply = provider._image_reply

        def _broken_device(text: str) -> dict:
            data = original_reply(text)
            data["items"][3]["device"] = "not_a_device"
            return data

        provider._image_reply = _broken_device
        provider._fix = {"replacements": []}
        workbench_jobs.PROVIDER = provider
        self._run_worker()

        rows = self._outputs(brief_id)
        validation = rows[0]["body_json"]["validation"]
        self.assertTrue(
            any(line.startswith("❌") and "items[4].device" in line for line in validation),
            validation,
        )

    def test_round_level_failure_not_reasked(self):
        brief_id = self._submit()
        provider = _ImageProvider(identity=_identity_reply(), image_task="believe_solution")
        original_reply = provider._image_reply

        def _same_layout(text: str) -> dict:
            data = original_reply(text)
            for item in data["items"]:
                item["layout"] = "candid_scene"
            return data

        provider._image_reply = _same_layout
        workbench_jobs.PROVIDER = provider
        self._run_worker()

        fix_calls = [c for c in provider.calls if "這些欄位沒有通過驗證，只重新回答這些" in c]
        self.assertEqual(len(fix_calls), 0, "round-level failure must not trigger a fix call")
        rows = self._outputs(brief_id)
        validation = rows[0]["body_json"]["validation"]
        self.assertTrue(
            any(line.startswith("❌") and "items_layouts" in line for line in validation),
            validation,
        )


if __name__ == "__main__":
    unittest.main()
