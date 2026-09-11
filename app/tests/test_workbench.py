"""app/tests/test_workbench.py — ticket workbench/02: the two tables, repository, one
generation job (dormant, no route, no screen — nothing outside app/tests calls this package
yet). FakeProvider only, no real network request; the fix-round-runs-once behaviour is ADR
0068 §6's money line (one paid call per re-ask, never a second), and coordinate/tenant
isolation are the other two of the全域 CLAUDE.md test four categories this file covers.
"""

import json
import unittest
from pathlib import Path

import app.background as background_module
import app.shared.web as web
import app.workbench as workbench_module
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.llm import providers
from app.schedule import repository as schedule_repo
from app.schedule import state as schedule_state
from app.workbench import jobs as workbench_jobs
from app.workbench import prompts as workbench_prompts
from app.workbench import repository as workbench_repo

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = REPO_ROOT / "app" / "methodology" / "image-prompt-template.md"
DEPARTMENT_PATH = REPO_ROOT / "app" / "departments" / "workbench" / "image_prompt.md"

ACTOR = "測試員"

def _cjk(n: int) -> str:
    """n 個中文字（不含換行）——灌出剛好落在某個字數帶的假文案，不必手動數字數。"""
    base = "測試文案內容真實好用推薦體驗品質細節故事風格"
    return (base * (n // len(base) + 1))[:n]


def _fake(rendered_output: str) -> providers.FakeProvider:
    return providers.FakeProvider(response=providers.ProviderResponse(
        output_text=rendered_output, structured=None,
        usage=providers.Usage(input_tokens=500, output_tokens=200), stop_reason="end_turn",
    ))


class _SequenceProvider:
    """跟 `providers.FakeProvider` 同一個呼叫介面，依序回傳不同的回覆——測試 3「一次修正輪」
    需要初次呼叫與修正呼叫給不同內容，`FakeProvider` 本身只認一個固定回覆。"""

    name = "fake"

    def __init__(self, outputs: list):
        self._outputs = list(outputs)
        self.calls: list = []

    def complete(self, *, model, system, messages, max_tokens, timeout_s=120.0,
                 effort=None, tools=None, org_id=None) -> providers.ProviderResponse:
        self.calls.append({"messages": messages})
        text = self._outputs[len(self.calls) - 1]
        return providers.ProviderResponse(
            output_text=text, structured=None,
            usage=providers.Usage(input_tokens=500, output_tokens=200), stop_reason="end_turn",
        )


class _WorkbenchTestBase(unittest.TestCase):
    def setUp(self):
        workbench_module.register_tasks()
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：素材工作檯", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        self.product = bi_repo.create_product(
            web.conn, self.brand_id, name="測試產品：晨光咖啡豆", actor=ACTOR,
        )
        # 座標詞彙表是 app.schedule 的表，工作檯只讀（repository.py 檔頭）；測試用 schedule
        # 既有的種子函式播種，再撿真的 label 組回覆，不手刻中文字串（種子內容變了測試不必
        # 跟著改）。
        coordinate_rows = schedule_repo.list_coordinates(web.conn, self.org_id, self.brand_id)
        self.coordinates = {
            dim: next(r["label"] for r in coordinate_rows if r["dimension"] == dim)
            for dim in workbench_prompts.COORDINATE_KEYS
        }
        self._orig_provider = workbench_jobs.PROVIDER

    def tearDown(self):
        workbench_jobs.PROVIDER = self._orig_provider

    def _run_worker(self) -> None:
        web.conn.commit()
        background_module.app().run_worker(wait=False)

    def _submit(self, **overrides) -> str:
        # F02-I02：`submit_brief` 不再是公開入口（一份素材組一定屬於一個 pack，
        # ARCHITECTURE.md §5.4）——`create_brief()` 幫這條舊路徑自動開一個單組任務包，
        # 行為跟之前直接呼叫 `workbench_module.submit_brief` 相容。
        brief = {
            "source_kind": "manual", "source_ref": {},
            "product_id": self.product["id"], "coordinates": {}, "visual_tone": None,
            "visual_concept": None, "style_key": "ugc", "request": {"parts": ["copy"]},
        }
        brief.update(overrides)
        return workbench_repo.create_brief(web.conn, self.org_id, self.brand_id, brief)

    def _copy_reply(self) -> dict:
        """ARCHITECTURE.md §5.6：一輪 5 組完整廣告——預設工單沒給 `copy_length`，`jobs._run`
        落回 `"short"`，這裡 5 組的 `body` 都落在短版字數帶。"""
        return {
            "coordinates": dict(self.coordinates),
            "sets": [
                {"body": _cjk(140), "headline": _cjk(10), "description": _cjk(15)}
                for _ in range(5)
            ],
            # 票 05（ADR 0068 §5 amendment）：文案回覆現在也帶視覺方向。
            "visual_tone": "暖調生活", "visual_concept": "測試視覺概念",
            "warnings": [],
        }

    def _outputs(self, brief_id: str, part: str) -> list:
        rows = web.conn.execute(
            "SELECT * FROM workbench_output WHERE brief_id = %s AND part = %s"
            " ORDER BY generation_round, version_index", (brief_id, part),
        ).fetchall()
        return [dict(r) for r in rows]


# -- 票 05（ADR 0069 §3）：`brief_text()` 是純函式，不需要 DB fixture -------------------

class BriefCoordinatesTextTest(unittest.TestCase):
    _STYLE = {"key": "ugc", "label": "UGC", "style_block": "手機直式實拍，低真實感提示"}

    def test_states_the_coordinates_when_a_snapshot_is_present(self):
        text = workbench_prompts.brief_text(
            {"coordinates_snapshot_json": {"angle": "UGC 偽裝"}, "visual_tone": None,
             "visual_concept": None, "request_json": {}},
            "測試產品", self._STYLE,
        )
        self.assertIn("這個節點的座標（文案照這組座標寫）：", text)
        self.assertIn(json.dumps({"angle": "UGC 偽裝"}, ensure_ascii=False), text)

    def test_says_nothing_about_coordinates_without_a_snapshot(self):
        """沒有快照（`coordinates_snapshot_json` 是 `None`）就不印這一行——跟舊語意共用
        「座標」兩字，分開斷言才擋得住只改一半的復原。"""
        text = workbench_prompts.brief_text(
            {"coordinates_snapshot_json": None, "visual_tone": None,
             "visual_concept": None, "request_json": {}},
            "測試產品", self._STYLE,
        )
        self.assertNotIn("這個節點的座標", text)
        self.assertNotIn("既有座標", text)


# -- 票 F01-T03-I01：方法論＋部門任務檔的圖片提示詞形狀，讀檔即可，不用 DB ---------------

# Fixed text 1（issue 原文）：圖上文字與數字規則，逐字在兩份檔各出現一次。
_RULE_BLOCK_LINES = (
    "1. 工作單上的「可用的大標（可用可不用）」只是參考：可以沿用、改寫或不用；"
    "沒有這一行時，回覆照樣完整。",
    "2. 大標、副標與每張圖的圖上文字，都是為這張圖新寫的文案；可用字句不是用字清單，"
    "不限制怎麼寫。唯一的限制是第 3 條。",
    "3. 圖上的數字與事實（價格、折扣、規格、認證）必須逐字出現在可用字句或品牌上下文裡，"
    "兩處都找不到的數字不上圖；工作單沒有可用字句這一行時，品牌上下文裡逐字出現的數字"
    "照樣可用。",
    "4. 回傳的大標、副標與圖上文字不加「」，外殼組提示詞時會加上。",
)

# Fixed text 2（issue 原文）：模板檔的開場段。
_TEMPLATE_INTRO = (
    "外殼組出每一則提示詞，模型只回欄位。模式看工單來源：檔期派工的工單走變體模式"
    "（先 ① 再 ②），手動開的工單走探索模式（先 ③ 再 ②）；沒有內容的行整行不出現。"
)

# 三個提示詞骨架的每一行（issue「Done」段落逐字給的 fenced block）。
_SKELETON_LINES = (
    "【風格】<style_block>",
    "【商品】<商品句>",
    "【受眾】<受眾>；痛點：<痛點>",
    "【這則的訴求】切角：<切角>——<切角說明>；標題公式：<標題公式>——<標題公式說明>",
    "【可用字句（逐字，不得改）】<可用字句，以／相連>",
    "【畫面】<scene>／<person>／<subject_position>",
    "【圖上文字】大標：「<headline>」；副標：「<subhead>」；文字純色填滿，數字獨立成行",
    "【輸出】<格式>（<格式說明>），一張",
    "以附上的這張圖為基底，分別生成 <N> 個完全不同風格排版與人物的圖片，主要訴求保持不變。"
    "一次一張。",
    "不變：訴求「<訴求句>」、可用字句「<可用字句，以／相連>」（數字逐字）、商品外型與 Logo、"
    "<輸出句>。",
    "可變：場景、人物、構圖、文字排版位置、配色。",
    "【目的與對象】<目的與對象>",
    "【任務】分別給我 <N> 張圖，每張一個不同的說服切角，排版與風格彼此差異要大：",
    "1. <name>｜<brief>｜圖上文字：「<on_image_line>」",
    "<N>. <name>｜<brief>｜圖上文字：「<on_image_line>」",
    "【圖上文字】每張圖只出現它自己那一行字；文字純色填滿，數字獨立成行",
)

# Fixed text 3（issue 原文）：image_prompt.md 的「## 回覆」段，逐字比對。
_REPLY_SECTION = "\n".join((
    "## 回覆——依工單的模式只回下面其中一個物件，物件前後不加任何文字或符號",
    "",
    "變體模式時，整段回覆就是這個形狀的物件：",
    "",
    "{",
    '  "hero": {',
    '    "scene": "……一句話的場景……",',
    '    "person": "……照受眾座標寫：是誰、在做什麼、露不露臉……",',
    '    "subject_position": "……商品或人物的位置、畫面佔比、鏡位、留白……",',
    '    "headline": "……這張圖的大標……",',
    '    "subhead": "……這張圖的副標……"',
    "  },",
    '  "warnings": []',
    "}",
    "",
    "沒有副標時，subhead 填 JSON 的 null。",
    "",
    "探索模式時，整段回覆就是這個形狀的物件，angles 的項數等於工單的角度數：",
    "",
    "{",
    '  "angles": [',
    '    {"name": "……creative-matrix.md 第一節的一個切角……", "brief": '
    '"……一句話的場景與排版……", "on_image_line": "……這張圖上唯一的一行字……"},',
    '    {"name": "……另一個切角……", "brief": "……排版和上一張差很多……", '
    '"on_image_line": "……這張圖上唯一的一行字……"}',
    "  ],",
    '  "warnings": []',
    "}",
))


class ImagePromptMethodologyShapeTest(unittest.TestCase):
    def test_image_prompt_methodology_shapes(self):
        template_text = TEMPLATE_PATH.read_text(encoding="utf-8")
        department_text = DEPARTMENT_PATH.read_text(encoding="utf-8")

        for line in _SKELETON_LINES:
            self.assertIn(line, template_text)

        for line in _RULE_BLOCK_LINES:
            self.assertEqual(template_text.count(line), 1, line)
            self.assertEqual(department_text.count(line), 1, line)

        self.assertIn(_TEMPLATE_INTRO, template_text)
        intro_zone = template_text.split("# 圖片提示詞模板", 1)[1].split("## 1.", 1)[0]
        self.assertNotIn("座標", intro_zone)

        self.assertIn("來源:", template_text)
        self.assertIn("最後查證日: 2026-09-10", template_text)
        for forbidden in (
            "来源", "逐字取自", "200～250", "固定段", "禁止：", "visual_tone",
            "視覺調性", "视觉调性", "【角度數量】", "有節點座標",
        ):
            self.assertNotIn(forbidden, template_text, forbidden)

        self.assertIn("模式：變體模式", department_text)
        self.assertIn("模式：探索模式；角度數：", department_text)
        self.assertIn("可用的大標（可用可不用）", department_text)
        for forbidden in (
            "附上的標題", "逐字取自", "visual_tone", "視覺調性", "视觉调性", "用「」包",
        ):
            self.assertNotIn(forbidden, department_text, forbidden)
        pre_deliverable = department_text.split("## 你拿到什麼", 1)[0]
        self.assertNotIn("座標", pre_deliverable)

        self.assertEqual(department_text.count("## 回覆"), 1)
        reply_zone = "## 回覆" + department_text.split("## 回覆", 1)[1]
        self.assertEqual(reply_zone.strip(), _REPLY_SECTION.strip())

        self.assertEqual(department_text.count("```"), 1)


# -- 案例 1：手動 copy 工單，走完整條 enqueue -> worker -> 一列 workbench_output --------

class ManualCopyBriefTest(_WorkbenchTestBase):
    def test_submit_then_worker_writes_one_all_green_output(self):
        brief_id = self._submit()

        self.assertTrue(background_module.is_active(f"workbench:{brief_id}:copy"))
        brief = workbench_repo.get_brief(web.conn, self.org_id, self.brand_id, brief_id)
        self.assertEqual(brief["status"], "queued")

        workbench_jobs.PROVIDER = _fake(json.dumps(self._copy_reply(), ensure_ascii=False))
        self._run_worker()

        self.assertFalse(background_module.is_active(f"workbench:{brief_id}:copy"))
        brief = workbench_repo.get_brief(web.conn, self.org_id, self.brand_id, brief_id)
        self.assertEqual(brief["status"], "done")

        # F02-I02（ARCHITECTURE.md §5.2）：一輪 copy 寫 `COPY_SET_COUNT`（5）列版本，
        # `version_index` 1..5，每一列的 `body_json` 都是同一份整輪回覆（`schedule/
        # state.py::_copy_summary()` 讀任何一列的 `sets` 都要看到全部 5 組）。
        rows = self._outputs(brief_id, "copy")
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(r["generation_round"] == 1 for r in rows))
        self.assertEqual([r["version_index"] for r in rows], [1, 2, 3, 4, 5])
        validation = rows[0]["body_json"]["validation"]
        self.assertTrue(validation)
        self.assertTrue(all(line.startswith("✅") for line in validation), validation)


# -- 案例 2：回覆夾散文 -> JSON-only 擋下，brief failed，沒有輸出列 --------------------

class ProseWrappedReplyTest(_WorkbenchTestBase):
    def test_prose_around_json_fails_the_brief(self):
        brief_id = self._submit()
        payload = (
            "以下是文案：" + json.dumps(self._copy_reply(), ensure_ascii=False)
            + "\n以上供您參考。"
        )
        workbench_jobs.PROVIDER = _fake(payload)
        self._run_worker()

        brief = workbench_repo.get_brief(web.conn, self.org_id, self.brand_id, brief_id)
        self.assertEqual(brief["status"], "failed")
        self.assertEqual(brief["last_error"], "代理沒有回傳純 JSON，請重新產出一次。")
        self.assertEqual(self._outputs(brief_id, "copy"), [])


# -- 案例 3：image_prompt 修正輪與渲染的完整跑一次（票 F01-T03-I02 的新形狀由
# `DispatchedImagePromptRunTest` 與 `test_workbench_image_prompt.py` 覆蓋）；本檔留下的
# 案例 4 換成新的 exploration 模式回覆形狀，驗證回合數／採用邏輯不受形狀變更影響。

# -- 案例 4：第二輪寫 generation_round=2；採用第一輪只標到那一列；adopted_output() 讀回 ---

def _exploration_reply(*angle_names: str) -> str:
    return json.dumps({
        "angles": [
            {"name": name, "brief": f"{name} 場景", "on_image_line": f"{name}文案"}
            for name in angle_names
        ],
        "warnings": [],
    }, ensure_ascii=False)


class ImagePromptRoundsAndAdoptionTest(_WorkbenchTestBase):
    def test_second_round_and_single_row_adoption(self):
        # 同上一個案例：`image_prompt_count` 是 `"image_prompt"` 在 `parts` 裡時的必填欄。
        # 預設 `source_kind="manual"` -> 探索模式，`angles` 項數等於 count。
        brief_id = self._submit(
            request={"parts": ["image_prompt"], "image_prompt_count": 2},
        )
        reply = _exploration_reply("省時", "健康")

        workbench_jobs.PROVIDER = _fake(reply)
        self._run_worker()
        rows = self._outputs(brief_id, "image_prompt")
        self.assertEqual([r["generation_round"] for r in rows], [1])
        round1_id = rows[0]["id"]

        # 第二輪：票 03 之後真的會做的「重新產出」——同一把 lock 已經處理完（狀態不再是
        # todo），background 契約的唯一索引只蓋 status='todo'，可以再排一次。
        background_module.enqueue(
            "background.workbench_generate", org_id=self.org_id,
            lock=f"workbench:{brief_id}:image_prompt",
            brand_id=self.brand_id, brief_id=brief_id, part="image_prompt", count=2,
        )
        workbench_jobs.PROVIDER = _fake(reply)
        self._run_worker()
        rows = self._outputs(brief_id, "image_prompt")
        self.assertEqual([r["generation_round"] for r in rows], [1, 2])
        round2_id = rows[1]["id"]

        # 還沒有人採用：回最新一輪（round 2）。
        before = workbench_module.adopted_output(
            web.conn, self.org_id, self.brand_id, brief_id, "image_prompt"
        )
        self.assertEqual(before["id"], round2_id)
        self.assertFalse(before["is_adopted"])

        adopted = workbench_repo.adopt_output(web.conn, self.org_id, self.brand_id, round1_id)
        self.assertIsNotNone(adopted["adopted_at"])

        # round 2 本身沒被動過。
        rows_after = self._outputs(brief_id, "image_prompt")
        round2_row = next(r for r in rows_after if r["id"] == round2_id)
        self.assertIsNone(round2_row["adopted_at"])

        after = workbench_module.adopted_output(
            web.conn, self.org_id, self.brand_id, brief_id, "image_prompt"
        )
        self.assertEqual(after["id"], round1_id)
        self.assertTrue(after["is_adopted"])


# -- 案例 5：briefs_for_source 的租戶隔離——同一個 source_tree_task_id，兩個組織 ----------

class SourceIsolationTest(_WorkbenchTestBase):
    def test_briefs_for_source_never_crosses_org(self):
        org_b = "org_workbench_test_isolation"
        web.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (org_b, org_b),
        )
        brand_b = bi_repo.create_brand(
            web.conn, org_id=org_b, name="測試品牌 B：素材工作檯隔離", client_name=None,
            actor=ACTOR,
        )
        web.conn.commit()

        # 這支測試只驗讀取面的租戶隔離，`parts`／`image_prompt_count` 給最小合法值滿足
        # `submit_brief()` 的驗證就好，跟隔離本身無關。
        source_ref = {"source_tree_task_id": "llm_shared_task_id_123"}
        self._submit(
            source_kind="schedule_node", source_ref=source_ref,
            request={"parts": ["image_prompt"], "image_prompt_count": 1},
        )
        workbench_repo.create_brief(
            web.conn, org_b, brand_b["id"],
            {"source_kind": "schedule_node", "source_ref": source_ref,
             "product_id": None, "coordinates": {}, "visual_tone": None,
             "visual_concept": None, "style_key": "ugc",
             "request": {"parts": ["image_prompt"], "image_prompt_count": 1}},
        )

        found = workbench_module.briefs_for_source(
            web.conn, self.org_id, self.brand_id, "schedule_node", source_ref
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["brand_id"], self.brand_id)
        self.assertEqual(found[0]["org_id"], self.org_id)
        # `parts` 永遠非空，所以剛送出的 brief 一律 'queued'（repository.py
        # `submit_brief()`：沒有「沒有 part 要跑」這個分支了）。
        self.assertEqual(found[0]["status"], "queued")


# -- 案例 6：product_id 指到別的組織 -> submit_brief 在 INSERT 之前就炸，沒有殘留列 --------

class ProductOwnershipTest(_WorkbenchTestBase):
    def test_cross_org_product_id_rejected_before_insert(self):
        org_b = "org_workbench_test_product_ownership"
        web.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (org_b, org_b),
        )
        brand_b = bi_repo.create_brand(
            web.conn, org_id=org_b, name="測試品牌 B：product owner", client_name=None,
            actor=ACTOR,
        )
        product_b = bi_repo.create_product(
            web.conn, brand_b["id"], name="測試產品 B", actor=ACTOR,
        )
        web.conn.commit()

        with self.assertRaises(ValueError) as ctx:
            self._submit(product_id=product_b["id"])
        self.assertEqual(str(ctx.exception), "product_unknown")

        count = web.conn.execute(
            "SELECT count(*) AS n FROM workbench_brief WHERE brand_id = %s", (self.brand_id,)
        ).fetchone()["n"]
        self.assertEqual(count, 0)

        # 自己組織自己的 product_id 照樣過。
        brief_id = self._submit(product_id=self.product["id"])
        self.assertIsNotNone(brief_id)


# -- 案例 7：影片腳本，count=2 全數綠燈；回覆只給 1 支 -> 修正輪不補齊 -> 老實印 ❌ ------

def _video_script(title: str) -> dict:
    return {
        "title": title, "framework": "PAS", "hook": "還在為早餐麻煩？",
        "beats": [
            {"t": "0-3s", "visual": "特寫商品", "voice": "口白一", "text": "字卡一"},
            {"t": "3-10s", "visual": "沖泡過程", "voice": "口白二", "text": "字卡二"},
            {"t": "10-20s", "visual": "飲用畫面", "voice": "口白三", "text": "字卡三"},
        ],
        "cta": "立即選購",
    }


class VideoScriptRoundTripTest(_WorkbenchTestBase):
    def test_count_2_round_trip_all_green(self):
        brief_id = self._submit(
            request={"parts": ["video_script"], "video_script_count": 2},
        )
        reply = json.dumps({
            "scripts": [_video_script("腳本一"), _video_script("腳本二")],
            "hook_pool": ["hook1", "hook2"], "warnings": [],
        }, ensure_ascii=False)
        workbench_jobs.PROVIDER = _fake(reply)
        self._run_worker()

        brief = workbench_repo.get_brief(web.conn, self.org_id, self.brand_id, brief_id)
        self.assertEqual(brief["status"], "done")
        # F02-I02（ARCHITECTURE.md §5.2）：一輪 video_script 一支腳本一列版本——這裡兩支
        # 都綠燈，所以是兩列。
        rows = self._outputs(brief_id, "video_script")
        self.assertEqual(len(rows), 2)
        validation = rows[0]["body_json"]["validation"]
        self.assertTrue(validation)
        self.assertTrue(all(line.startswith("✅") for line in validation), validation)

    def test_short_reply_stays_red_after_a_fix_round_that_does_not_add_one(self):
        """票面 contradiction check 第二條：修正輪回覆刻意不補第二支（`replacements: []`），
        證明「批次不重生」——不是靠假設修正輪一定會把數量補齊才轉綠。"""
        brief_id = self._submit(
            request={"parts": ["video_script"], "video_script_count": 2},
        )
        initial_reply = json.dumps({
            "scripts": [_video_script("腳本一")], "hook_pool": ["hook1", "hook2"], "warnings": [],
        }, ensure_ascii=False)
        fix_reply = json.dumps({"replacements": []}, ensure_ascii=False)
        provider = _SequenceProvider([initial_reply, fix_reply])
        workbench_jobs.PROVIDER = provider
        self._run_worker()

        self.assertEqual(len(provider.calls), 2, "只准問一次修正，不准第三通")
        brief = workbench_repo.get_brief(web.conn, self.org_id, self.brand_id, brief_id)
        self.assertEqual(brief["status"], "done")
        rows = self._outputs(brief_id, "video_script")
        validation = rows[0]["body_json"]["validation"]
        fail = next(line for line in validation if line.split("：", 1)[0].endswith("scripts"))
        self.assertTrue(fail.startswith("❌"), fail)


# -- 案例 8：自由生成，items 回存；空清單 -> 修正輪換成非空但空字串 -> 逐項驗證仍是 ❌ ------

class FreeRoundTripTest(_WorkbenchTestBase):
    def test_items_round_trip_all_green(self):
        brief_id = self._submit(
            request={"parts": ["free"], "free_text": "寫三句 IG 限動貼文"},
        )
        items = [{"label": "第一句", "value": "文案一"}, {"label": "第二句", "value": "文案二"}]
        reply = json.dumps({"items": items, "warnings": []}, ensure_ascii=False)
        workbench_jobs.PROVIDER = _fake(reply)
        self._run_worker()

        brief = workbench_repo.get_brief(web.conn, self.org_id, self.brand_id, brief_id)
        self.assertEqual(brief["status"], "done")
        rows = self._outputs(brief_id, "free")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["body_json"]["items"], items)
        validation = rows[0]["body_json"]["validation"]
        self.assertTrue(validation)
        self.assertTrue(all(line.startswith("✅") for line in validation), validation)

    def test_empty_list_then_empty_strings_both_stay_red(self):
        """票面 contradiction check 第三條：最便宜的錯誤實作是收 `{"label": "", "value": ""}`
        （型別對、非空清單，但內容是空字串）——修正輪刻意換成這種形狀，驗證程式檢查的是
        內容而不只是清單長度。"""
        brief_id = self._submit(
            request={"parts": ["free"], "free_text": "寫三句 IG 限動貼文"},
        )
        initial_reply = json.dumps({"items": [], "warnings": []}, ensure_ascii=False)
        fix_reply = json.dumps({
            "replacements": [{"path": "items", "value": [{"label": "", "value": ""}]}],
        }, ensure_ascii=False)
        provider = _SequenceProvider([initial_reply, fix_reply])
        workbench_jobs.PROVIDER = provider
        self._run_worker()

        self.assertEqual(len(provider.calls), 2, "只准問一次修正，不准第三通")
        brief = workbench_repo.get_brief(web.conn, self.org_id, self.brand_id, brief_id)
        self.assertEqual(brief["status"], "done")
        rows = self._outputs(brief_id, "free")
        validation = rows[0]["body_json"]["validation"]
        fail = next(line for line in validation if line.split("：", 1)[0].endswith("items[1]"))
        self.assertTrue(fail.startswith("❌"), fail)


# -- 案例 9：copy 回覆的 warnings 過濾成純字串；完全沒有這個鍵退回空清單 -----------------

class CopyWarningsSummaryTest(_WorkbenchTestBase):
    def test_mixed_and_missing_warnings(self):
        """票 workbench-2/02（ablation §4）：`app/schedule/state.py::_copy_summary()` 把
        `body_json.warnings` 過濾成純字串清單——混進來的非字串元素被濾掉（不是「全部都是
        字串才收」，也不是整批丟棄），完全沒有這個鍵的回覆退回空清單，不是缺鍵炸掉。直接
        呼叫 `_copy_summary()`（不是重測 `submit_brief`／worker 那條路徑，那條路徑其他七支
        案例已經驗過），證明它讀的是這個模組自己寫出來的 `workbench_output` 列。先證過紅：
        把 `warnings` 那一行從 `_copy_summary()` 拿掉，這支立刻兩個斷言都紅
        （`KeyError`／`AssertionError`）。"""
        brief_id = self._submit()
        reply = self._copy_reply()
        reply["warnings"] = ["3 顆體驗包的價格是佔位，投放前請核對。", "另一句提醒。", 123]
        workbench_jobs.PROVIDER = _fake(json.dumps(reply, ensure_ascii=False))
        self._run_worker()
        output = workbench_module.adopted_output(
            web.conn, self.org_id, self.brand_id, brief_id, "copy"
        )
        summary = schedule_state._copy_summary(output)
        self.assertEqual(
            summary["warnings"],
            ["3 顆體驗包的價格是佔位，投放前請核對。", "另一句提醒。"],
        )

        brief_id_2 = self._submit()
        reply_2 = self._copy_reply()
        del reply_2["warnings"]
        workbench_jobs.PROVIDER = _fake(json.dumps(reply_2, ensure_ascii=False))
        self._run_worker()
        output_2 = workbench_module.adopted_output(
            web.conn, self.org_id, self.brand_id, brief_id_2, "copy"
        )
        self.assertEqual(schedule_state._copy_summary(output_2)["warnings"], [])


# -- 案例 9b（票 F02-I01）：`_copy_summary()` 從 `sets` 拆出 index-aligned 的三個舊清單 -----

class CopySummaryReadsIndexAlignedListsFromSetsTest(unittest.TestCase):
    def test_five_sets_become_three_index_aligned_lists(self):
        output = {
            "is_adopted": True, "generation_round": 1,
            "body_json": {
                "copy_length": "short",
                "sets": [
                    {"body": "身1", "headline": "標1", "description": "說1"},
                    {"body": "身2", "headline": "標2", "description": "說2"},
                ],
                "visual_tone": None, "visual_concept": "概念", "warnings": [], "validation": [],
            },
        }
        summary = schedule_state._copy_summary(output)
        self.assertEqual(summary["bodies"], ["身1", "身2"])
        self.assertEqual(summary["headlines"], ["標1", "標2"])
        self.assertEqual(summary["descriptions"], ["說1", "說2"])


# -- 案例 10（票 F01-T03-I02）：schedule_node 派工的 image_prompt，沒有已採用文案 -------
# 也能跑完整條 submit -> worker -> 一列 workbench_output，寫出變體模式的 hero／variant 渲染。

class DispatchedImagePromptRunTest(_WorkbenchTestBase):
    def test_image_prompt_run_without_adopted_copy_renders_hero_and_variant(self):
        brief_id = self._submit(
            source_kind="schedule_node",
            source_ref={"node_key": "1.1.1", "source_tree_task_id": "llm_runtime_test"},
            request={"parts": ["image_prompt"], "image_prompt_count": 1},
        )
        reply = json.dumps({
            "hero": {
                "scene": "台灣公寓廚房的晨光", "person": "一位女性，居家便服，露出笑容",
                "subject_position": "商品置中，中景，畫面留白給文字",
                "headline": "早晨也能好好吃", "subhead": "一杯搞定忙碌早晨",
            },
            "warnings": [],
        }, ensure_ascii=False)
        workbench_jobs.PROVIDER = _fake(reply)
        self._run_worker()

        brief = workbench_repo.get_brief(web.conn, self.org_id, self.brand_id, brief_id)
        self.assertEqual(brief["status"], "done")

        rows = self._outputs(brief_id, "image_prompt")
        self.assertEqual(len(rows), 1)
        body = rows[0]["body_json"]
        self.assertEqual(body["mode"], "variant")
        rendered = body["rendered"]
        self.assertNotIn("exploration", rendered)
        self.assertIsInstance(rendered["hero"], str)
        self.assertTrue(rendered["hero"])
        self.assertIsInstance(rendered["variant"], str)
        self.assertTrue(rendered["variant"])


if __name__ == "__main__":
    unittest.main()
