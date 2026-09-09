"""app/tests/test_workbench.py — ticket workbench/02: the two tables, repository, one
generation job (dormant, no route, no screen — nothing outside app/tests calls this package
yet). FakeProvider only, no real network request; the fix-round-runs-once behaviour is ADR
0068 §6's money line (one paid call per re-ask, never a second), and coordinate/tenant
isolation are the other two of the全域 CLAUDE.md test four categories this file covers.
"""

import json
import unittest
from unittest import mock

import app.background as background_module
import app.shared.web as web
import app.workbench as workbench_module
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.llm import providers
from app.schedule import repository as schedule_repo
from app.workbench import jobs as workbench_jobs
from app.workbench import prompts as workbench_prompts
from app.workbench import repository as workbench_repo

ACTOR = "測試員"

IMAGE_FIXED = {
    "format": "4:5｜Meta 動態消息", "capture_style": "UGC 手機實拍，現場光",
    "human": "一位女性，居家便服", "must_keep": "商品輪廓、Logo", "forbidden": "卡通感、AI 感",
}
# 校準過（scripts/workbench_probe.py 的渲染函式量出來）：204 字，落在 200～250 字範圍內。
_BASE_ENVIRONMENT = "台灣公寓廚房，晨光斜射進來，桌上還有沒收的早報與購物清單，窗邊掛著曬乾的抹布"
# 265 字，超出 200～250 字範圍——修正輪「還是不合格」那條分支用的真實（非造假）超字版本。
LONG_ENVIRONMENT = (
    "台灣公寓廚房，晨光斜射進來，桌上還有沒收的早報，流理台旁堆著昨晚的碗盤與購物袋，"
    "冰箱門上貼著小孩畫的圖畫紙與購物清單便利貼，還有一疊還沒拆開的網購包裹紙箱堆在牆角，"
    "牆上時鐘指著七點半，窗簾只拉開一半"
)


def _image_variable(index: int, environment: str | None = None) -> dict:
    return {
        "index": index, "theme": "早晨廚房", "text": "一杯搞定早餐",
        "environment": environment or _BASE_ENVIRONMENT,
        "subject": "置中，中景，焦點在商品，畫面留白給文字，背景略為模糊",
        "relation": "咖啡杯在右前景，手部從畫面外伸入",
        "authenticity": "流理台有使用痕跡、杯緣有水漬、抹布隨手一放",
    }


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
        brief = {
            "kind": "copy", "source_kind": "manual", "source_ref": {},
            "product_id": self.product["id"], "coordinates": {}, "visual_tone": None,
            "visual_concept": None, "style_key": "ugc", "request": {},
        }
        brief.update(overrides)
        return workbench_module.submit_brief(
            web.conn, self.org_id, self.brand_id, brief, created_by=ACTOR,
        )

    def _copy_reply(self) -> dict:
        return {
            "coordinates": dict(self.coordinates),
            "short": [_cjk(140) for _ in range(5)],
            "medium": [_cjk(450) for _ in range(3)],
            "long": [_cjk(950) for _ in range(2)],
            "headlines": [_cjk(10) for _ in range(5)],
            "descriptions": [_cjk(15) for _ in range(5)],
            # 票 05（ADR 0068 §5 amendment）：文案回覆現在也帶視覺方向。
            "visual_tone": "暖調生活", "visual_concept": "測試視覺概念",
            "warnings": [],
        }

    def _outputs(self, brief_id: str, part: str) -> list:
        rows = web.conn.execute(
            "SELECT * FROM workbench_output WHERE brief_id = %s AND part = %s"
            " ORDER BY generation_round", (brief_id, part),
        ).fetchall()
        return [dict(r) for r in rows]


# -- 案例 1：手動 copy 工單，走完整條 enqueue -> worker -> 一列 workbench_output --------

class ManualCopyBriefTest(_WorkbenchTestBase):
    def test_submit_then_worker_writes_one_all_green_output(self):
        brief_id = self._submit(kind="copy")

        self.assertTrue(background_module.is_active(f"workbench:{brief_id}:copy"))
        brief = workbench_repo.get_brief(web.conn, self.org_id, self.brand_id, brief_id)
        self.assertEqual(brief["status"], "queued")

        workbench_jobs.PROVIDER = _fake(json.dumps(self._copy_reply(), ensure_ascii=False))
        self._run_worker()

        self.assertFalse(background_module.is_active(f"workbench:{brief_id}:copy"))
        brief = workbench_repo.get_brief(web.conn, self.org_id, self.brand_id, brief_id)
        self.assertEqual(brief["status"], "done")

        rows = self._outputs(brief_id, "copy")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["generation_round"], 1)
        validation = rows[0]["body_json"]["validation"]
        self.assertTrue(validation)
        self.assertTrue(all(line.startswith("✅") for line in validation), validation)


# -- 案例 2：回覆夾散文 -> JSON-only 擋下，brief failed，沒有輸出列 --------------------

class ProseWrappedReplyTest(_WorkbenchTestBase):
    def test_prose_around_json_fails_the_brief(self):
        brief_id = self._submit(kind="copy")
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


# -- 案例 3：image_prompt，第二則同時壞在固定段與字數 -> 修正輪只問一次、只點名它 --------

class ImagePromptFixRoundTest(_WorkbenchTestBase):
    def test_second_item_fix_runs_once_and_reports_honestly(self):
        # 票 03：`submit_brief()` 現在要求 `kind='image_prompt'` 手動送出時帶
        # `on_image_texts`（沒有 copy 輸出可以接）——`image_prompt_count` 本身的意思沒變。
        brief_id = self._submit(
            kind="image_prompt",
            request={"image_prompt_count": 4, "on_image_texts": ["一杯搞定早餐"]},
        )

        # 第 1／4 則是票 workbench/04 walk round 2 amendment 的新案例（原文點名
        # `prompts[1]` 那個型別守門案例），兩個都是「真實資料缺陷」（不靠渲染 mock，換幾次
        # 都不會自己好）：第 1 則字數帶本身超標，第 4 則整個物件缺一個鍵。第 2 則沿用原本的
        # 案例（固定段缺欄位，靠渲染 mock 只咬第一次渲染）。
        item1_initial = _image_variable(1, environment=LONG_ENVIRONMENT)
        item4_initial = {k: v for k, v in _image_variable(4).items() if k != "authenticity"}
        initial_reply = json.dumps({
            "fixed": IMAGE_FIXED,
            "prompts": [item1_initial, _image_variable(2), _image_variable(3), item4_initial],
            "warnings": [],
        }, ensure_ascii=False)
        # 修正輪回覆：第 1 則回一個型別不對的字串（票 workbench/04 walk round 2 那次真實壞掉
        # 的樣子：修正輪的回覆把物件換成一段散文）——型別守門要讓它被安靜跳過，原本超字的
        # 物件原封不動留著、依舊 ❌。第 2 則（沿用原案例）整個換掉、換成一個真的超過 250 字
        # 的版本——證明「修正過還是不合格」時老實印 ❌，不再問第三次。第 4 則回一個型別、鍵
        # 都合格的物件（補回被拿掉的鍵）——套用後應該轉 ✅。
        fix_reply = json.dumps({
            "replacements": [
                {"path": "prompts[1]", "value": "一段模型亂寫的散文，不是原本要的物件形狀"},
                {"path": "prompts[2]", "value": _image_variable(2, environment=LONG_ENVIRONMENT)},
                {"path": "prompts[4]", "value": _image_variable(4)},
            ],
        }, ensure_ascii=False)
        provider = _SequenceProvider([initial_reply, fix_reply])
        workbench_jobs.PROVIDER = provider

        # 第一次回覆的固定段其實逐字一致（同一個 `fixed`，見 ADR 0068 §7：固定段整份 brief
        # 只產一次、逐則比對）——「第二則的固定段被換掉」這件事在真實 JSON 形狀下造不出來，
        # 這裡改成在渲染那一層動手腳一次（只動第 2 則第一次被渲染的那一次，等長替換，長度
        # 帶不受影響，乾淨隔離「固定欄位逐字出現」這條規則），比照
        # `scripts/workbench_probe.py::_run_selftest` fixture 3 的手法。
        real_render = workbench_prompts.render_image_prompt
        call_state = {"item2_seen": 0}

        def corrupting_render(fixed, variable):
            text = real_render(fixed, variable)
            if variable.get("index") == 2:
                call_state["item2_seen"] += 1
                if call_state["item2_seen"] == 1:
                    return text.replace(fixed["human"], "＊" * len(fixed["human"]), 1)
            return text

        with mock.patch("app.workbench.validate.render_image_prompt",
                         side_effect=corrupting_render):
            self._run_worker()

        self.assertEqual(len(provider.calls), 2, "只准問一次修正，不准第三通")
        fix_prompt = provider.calls[1]["messages"][0]["content"]
        self.assertIn("prompts[1]", fix_prompt)
        self.assertIn("prompts[2]", fix_prompt)
        self.assertIn("prompts[4]", fix_prompt)
        self.assertNotIn("prompts[3]", fix_prompt)
        self.assertNotIn("WORKBENCH-IMAGE-PROMPT-TASK-V1", fix_prompt)  # 不重貼整份部門任務檔
        self.assertIn("## 這張工單", fix_prompt)  # 工單段重貼一次：每通呼叫都是無狀態的
        self.assertIn(json.dumps(item1_initial, ensure_ascii=False), fix_prompt)  # 原值原文
        self.assertIn(json.dumps(item4_initial, ensure_ascii=False), fix_prompt)  # 原值原文
        self.assertIn("回一個物件，鍵與原值相同", fix_prompt)  # 精確回覆形狀，數字用程式算

        brief = workbench_repo.get_brief(web.conn, self.org_id, self.brand_id, brief_id)
        self.assertEqual(brief["status"], "done")

        rows = self._outputs(brief_id, "image_prompt")
        self.assertEqual(len(rows), 1)
        validation = rows[0]["body_json"]["validation"]

        def _line(n: int) -> str:
            return next(
                line for line in validation if line.split("：", 1)[0].endswith(f"prompts[{n}]")
            )

        line1 = _line(1)
        self.assertTrue(line1.startswith("❌"), line1)
        # 型別不對被安靜跳過：原本超字的物件原封不動，問題描述還是原本那句，不是換成一句
        # 「缺欄位」或別的——這行紅了就代表型別守門被拿掉、字串真的蓋過了原本的物件。
        self.assertIn("超出 200～250 字範圍", line1)
        line2 = _line(2)
        self.assertTrue(line2.startswith("❌"), line2)
        self.assertTrue(_line(3).startswith("✅"), _line(3))
        line4 = _line(4)
        self.assertTrue(line4.startswith("✅"), line4)  # 型別、鍵都合格，套用後轉綠


# -- 案例 4：第二輪寫 generation_round=2；採用第一輪只標到那一列；adopted_output() 讀回 ---

class ImagePromptRoundsAndAdoptionTest(_WorkbenchTestBase):
    def test_second_round_and_single_row_adoption(self):
        # 票 03：同上一個案例，`on_image_texts` 是手動 image_prompt 工單的新必填欄。
        brief_id = self._submit(
            kind="image_prompt",
            request={"image_prompt_count": 2, "on_image_texts": ["一杯搞定早餐"]},
        )
        reply = json.dumps({
            "fixed": IMAGE_FIXED,
            "prompts": [_image_variable(1), _image_variable(2)],
            "warnings": [],
        }, ensure_ascii=False)

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

        # kind='image_prompt' 沒給 image_prompt_count：parts=[]，不排任何 job（ADR 0068 §7
        # 沒有預設張數）——這支測試只驗讀取面的租戶隔離，不需要、也不該碰佇列。
        # 票 03：`on_image_texts` 是手動 image_prompt 工單的新必填欄（submit 就會擋），跟
        # 這支測試要驗的隔離無關，給一則最小值滿足它就好。
        source_ref = {"source_tree_task_id": "llm_shared_task_id_123"}
        self._submit(
            kind="image_prompt", source_kind="schedule_node", source_ref=source_ref,
            request={"on_image_texts": ["一杯搞定早餐"]},
        )
        workbench_module.submit_brief(
            web.conn, org_b, brand_b["id"],
            {"kind": "image_prompt", "source_kind": "schedule_node", "source_ref": source_ref,
             "product_id": None, "coordinates": {}, "visual_tone": None,
             "visual_concept": None, "style_key": "ugc",
             "request": {"on_image_texts": ["一杯搞定早餐"]}},
            created_by=ACTOR,
        )

        found = workbench_module.briefs_for_source(
            web.conn, self.org_id, self.brand_id, "schedule_node", source_ref
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["brand_id"], self.brand_id)
        self.assertEqual(found[0]["org_id"], self.org_id)
        # 沒給 image_prompt_count -> parts=[] -> 沒有東西在排隊，brief 直接是 done（票 04
        # amendment 第 1 點；repository.py `submit_brief()` 不再一律寫 'queued'）。
        self.assertEqual(found[0]["status"], "done")


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
        brief_id = self._submit(kind="video_script", request={"video_script_count": 2})
        reply = json.dumps({
            "scripts": [_video_script("腳本一"), _video_script("腳本二")],
            "hook_pool": ["hook1", "hook2"], "warnings": [],
        }, ensure_ascii=False)
        workbench_jobs.PROVIDER = _fake(reply)
        self._run_worker()

        brief = workbench_repo.get_brief(web.conn, self.org_id, self.brand_id, brief_id)
        self.assertEqual(brief["status"], "done")
        rows = self._outputs(brief_id, "video_script")
        self.assertEqual(len(rows), 1)
        validation = rows[0]["body_json"]["validation"]
        self.assertTrue(validation)
        self.assertTrue(all(line.startswith("✅") for line in validation), validation)

    def test_short_reply_stays_red_after_a_fix_round_that_does_not_add_one(self):
        """票面 contradiction check 第二條：修正輪回覆刻意不補第二支（`replacements: []`），
        證明「批次不重生」——不是靠假設修正輪一定會把數量補齊才轉綠。"""
        brief_id = self._submit(kind="video_script", request={"video_script_count": 2})
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
        brief_id = self._submit(kind="free", request={"free_text": "寫三句 IG 限動貼文"})
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
        brief_id = self._submit(kind="free", request={"free_text": "寫三句 IG 限動貼文"})
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


if __name__ == "__main__":
    unittest.main()
