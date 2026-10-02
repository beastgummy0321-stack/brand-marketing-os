"""app/tests/test_workbench.py — ticket workbench/02: the two tables, repository, one
generation job (dormant, no route, no screen — nothing outside app/tests calls this package
yet). FakeProvider only, no real network request; the fix-round-runs-once behaviour is ADR
0068 §6's money line (one paid call per re-ask, never a second), and coordinate/tenant
isolation are the other two of the全域 CLAUDE.md test four categories this file covers.
"""

import json
import re
import unittest
import unittest.mock
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
from app.workbench import visual

REPO_ROOT = Path(__file__).resolve().parents[2]

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


_LOOK_LINE_RE = re.compile(r"- 第 (\d+) 則：([a-zA-Z_]+)（")

_DEVICE_CYCLE = list(visual.DEVICES)
_LAYOUT_CYCLE = list(visual.LAYOUTS)


def _image_item(i: int, look: str) -> dict:
    headline = f"文案{i}號"
    return {
        "title": f"點子{i}", "device": _DEVICE_CYCLE[i % len(_DEVICE_CYCLE)],
        "layout": _LAYOUT_CYCLE[i % len(_LAYOUT_CYCLE)], "look": look,
        "subject_role": "clear", "persuasion": "none", "headline": [headline],
        "prompt": (
            f"4:5 直式單圖廣告，情境示意畫面第 {i} 則，人物在明亮廚房裡拿著商品。"
            f"主標「{headline}」置中，純色填滿，不放其他文字。"
        ),
    }


def _image_reply() -> dict:
    return {"image_task": "believe_solution", "warnings": [], "items": [
        _image_item(i, "soft_lifestyle") for i in range(1, 11)
    ]}


class _ImageRoundProvider:
    """F07-I07：一個假供應商同時扮兩顆模型——`workbench_derive_identity`（`identity.py`
    先呼叫一次、之後讀快取）跟 `workbench_image_prompt`（每一輪一次，或加一次修正輪）。
    靠 prompt 內容分辨是哪一通：`identity.py` 的部門檔開頭是「品牌視覺總監」，修正輪的
    `fix.md` 固定帶「這些欄位沒有通過驗證，只重新回答這些」；其餘就是圖片提示詞正輪，
    讀 worksheet 的「- 第 N 則：<look>」那幾行，把系統分配的風格原樣填回每一項的 `look`
    （票面 Done：「reading each 「第 N 則：<key>」 line from the prompt and writing that
    key into item N's `look`」）。"""

    name = "fake"

    def __init__(self, *, identity: dict, fix: dict | None = None):
        self._identity = identity
        self._fix = fix
        self.calls: list = []

    def complete(self, *, model, system, messages, max_tokens, timeout_s=120.0,
                 effort=None, tools=None, org_id=None) -> providers.ProviderResponse:
        text = messages[0]["content"]
        self.calls.append(text)
        if "品牌視覺總監" in text:
            structured, output_text = self._identity, ""
        elif "這些欄位沒有通過驗證，只重新回答這些" in text and self._fix is not None:
            structured, output_text = None, json.dumps(self._fix, ensure_ascii=False)
        else:
            plan = {int(n): look for n, look in _LOOK_LINE_RE.findall(text)}
            reply = _image_reply()
            for i, item in enumerate(reply["items"], start=1):
                item["look"] = plan.get(i, item["look"])
            structured, output_text = reply, ""
        return providers.ProviderResponse(
            output_text=output_text, structured=structured,
            usage=providers.Usage(input_tokens=500, output_tokens=200), stop_reason="end_turn",
        )


def _identity_reply(**overrides) -> dict:
    base = {
        "identity": "都會生活感，人物二十到三十五歲，配色暖米大地色，情緒放鬆自在。",
        "fit_looks": ["soft_lifestyle", "documentary", "clean_bright"],
        "excluded_looks": [], "reason": "依品牌事實推導。",
    }
    base.update(overrides)
    return base


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
        # F38 decision 1: this brand registers no evidence, so the copy vocabulary only offers
        # the `none` proof kind — pick it by key.
        coordinate_rows = schedule_repo.list_coordinates(web.conn, self.org_id, self.brand_id)
        self.coordinates = {
            dim: next(r["label"] for r in coordinate_rows if r["dimension"] == dim
                      and (dim != "proof" or r["key"] == "none"))
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
    def test_states_the_coordinates_when_a_snapshot_is_present(self):
        text = workbench_prompts.brief_text(
            {"coordinates_snapshot_json": {"angle": "UGC 偽裝"}, "visual_tone": None,
             "visual_concept": None, "request_json": {}},
            "測試產品",
        )
        self.assertIn("這個節點的座標（文案照這組座標寫）：", text)
        self.assertIn(json.dumps({"angle": "UGC 偽裝"}, ensure_ascii=False), text)

    def test_says_nothing_about_coordinates_without_a_snapshot(self):
        """沒有快照（`coordinates_snapshot_json` 是 `None`）就不印這一行——跟舊語意共用
        「座標」兩字，分開斷言才擋得住只改一半的復原。"""
        text = workbench_prompts.brief_text(
            {"coordinates_snapshot_json": None, "visual_tone": None,
             "visual_concept": None, "request_json": {}},
            "測試產品",
        )
        self.assertNotIn("這個節點的座標", text)
        self.assertNotIn("既有座標", text)

    def test_carries_no_style_line(self):
        """F07-I09（Decision 25）：舊全域風格庫退休，`brief_text()` 不再帶「風格：」那一行
        （Y08：把它加回去要讓這條紅）。"""
        text = workbench_prompts.brief_text(
            {"coordinates_snapshot_json": None, "visual_tone": None,
             "visual_concept": None, "request_json": {}},
            "測試產品",
        )
        self.assertNotIn("風格", text)


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


# -- F47 W4：工單先 commit 再排工作；成功的一輪清掉舊的 last_error ---------------------------

class CommitBeforeEnqueueTest(_WorkbenchTestBase):
    def test_a_job_started_by_the_enqueue_finds_the_brief(self):
        """The worker reads on its own connection the instant a job is deferred: the brief
        must already be committed when `enqueue()` runs (drill 10 「找不到工單」)."""
        seen: list = []

        def enqueue_and_look(task_name, *, org_id, lock, brief_id, **kwargs):
            with coredb.connection() as other:
                row = other.execute(
                    "SELECT id FROM workbench_brief WHERE id = %s", (brief_id,),
                ).fetchone()
            seen.append(row is not None)
            return True

        with unittest.mock.patch.object(background_module, "enqueue", enqueue_and_look):
            self._submit()
        self.assertEqual(seen, [True])

    def test_a_successful_round_clears_the_old_error(self):
        brief_id = self._submit()
        workbench_jobs.PROVIDER = _fake("不是 JSON")
        self._run_worker()
        failed = workbench_repo.get_brief(web.conn, self.org_id, self.brand_id, brief_id)
        self.assertEqual(failed["status"], "failed")
        self.assertTrue(failed["last_error"])

        workbench_repo.run_part(web.conn, self.org_id, self.brand_id, brief_id, "copy")
        workbench_jobs.PROVIDER = _fake(json.dumps(self._copy_reply(), ensure_ascii=False))
        self._run_worker()
        brief = workbench_repo.get_brief(web.conn, self.org_id, self.brand_id, brief_id)
        self.assertEqual((brief["status"], brief["last_error"]), ("done", None))


# -- 案例 3／4（F07-I07 重寫）：一輪寫 10 列；第二輪 identity 讀快取不再問模型；採用其中
# 一列，`adopted_output()` 讀回那一列，其餘列不受影響 --------------------------------------

class ImagePromptRoundsAndAdoptionTest(_WorkbenchTestBase):
    def test_second_round_reuses_identity_and_one_row_can_be_adopted(self):
        brief_id = self._submit(request={"parts": ["image_prompt"]})

        workbench_jobs.PROVIDER = _ImageRoundProvider(identity=_identity_reply())
        self._run_worker()
        rows = self._outputs(brief_id, "image_prompt")
        self.assertEqual(len(rows), 10)
        self.assertTrue(all(r["generation_round"] == 1 for r in rows))
        round1_row_id = rows[0]["id"]

        # 第二輪：同一把 lock 已經處理完，可以再排一次。
        background_module.enqueue(
            "background.workbench_generate", org_id=self.org_id,
            lock=f"workbench:{brief_id}:image_prompt",
            brand_id=self.brand_id, brief_id=brief_id, part="image_prompt", count=None,
        )
        round2_provider = _ImageRoundProvider(identity=_identity_reply())
        workbench_jobs.PROVIDER = round2_provider
        self._run_worker()
        rows = self._outputs(brief_id, "image_prompt")
        self.assertEqual(len(rows), 20)
        self.assertEqual(sorted({r["generation_round"] for r in rows}), [1, 2])
        # Decision 20：一個 (brand, knowledge_version) 只推導一次——第二輪的這顆 provider
        # 完全沒被問過視覺識別，代表 `ensure_identity()` 讀的是快取。
        self.assertFalse(any("品牌視覺總監" in c for c in round2_provider.calls))

        before = workbench_module.adopted_output(
            web.conn, self.org_id, self.brand_id, brief_id, "image_prompt",
        )
        self.assertFalse(before["is_adopted"])

        adopted = workbench_repo.adopt_output(web.conn, self.org_id, self.brand_id, round1_row_id)
        self.assertIsNotNone(adopted["adopted_at"])

        after = workbench_module.adopted_output(
            web.conn, self.org_id, self.brand_id, brief_id, "image_prompt",
        )
        self.assertEqual(after["id"], round1_row_id)
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
    def test_dispatched_set_without_adopted_copy_still_writes_ten_rows(self):
        """F07-I07：`source_kind` 不再決定變體／探索模式（那個二分法整個退休）——一張排程
        派工的工單，就算還沒有任何已採用的 copy，一樣正常走完整條 10 列的生成。"""
        brief_id = self._submit(
            source_kind="schedule_node",
            source_ref={"node_key": "1.1.1", "source_tree_task_id": "llm_runtime_test"},
            request={"parts": ["image_prompt"]},
        )
        workbench_jobs.PROVIDER = _ImageRoundProvider(identity=_identity_reply())
        self._run_worker()

        brief = workbench_repo.get_brief(web.conn, self.org_id, self.brand_id, brief_id)
        self.assertEqual(brief["status"], "done")

        rows = self._outputs(brief_id, "image_prompt")
        self.assertEqual(len(rows), 10)
        body = rows[0]["body_json"]
        self.assertIsNone(body["cards"])
        self.assertIn("品牌視覺規範：", body["text"])
        self.assertIn("風格規範：", body["text"])
        validation = body["validation"]
        self.assertTrue(all(line.startswith("✅") for line in validation), validation)


# -- 案例 9（F07-I09 Done 9）：舊全域風格庫退休——`style_key` 接了就丟，非預設值
# 「no_such_style」全程不炸、不影響輸出，也不出現在送給模型的 prompt 裡 -----------------------

class StyleKeyIgnoredTest(_WorkbenchTestBase):
    def test_submit_brief_with_unknown_style_key_does_not_raise(self):
        """Y02：`submit_brief()`（經 `_submit`／`create_brief` 轉呼叫）接了就丟，不驗證
        `style_key`——非預設值不炸。"""
        brief_id = self._submit(style_key="no_such_style")
        self.assertIsNotNone(brief_id)

    def test_stored_style_key_is_always_the_column_default(self):
        """Y05：INSERT 不列 `style_key`，欄位的 DEFAULT 'ugc' 填——即使呼叫端送了別的值。"""
        brief_id = self._submit(style_key="no_such_style")
        row = web.conn.execute(
            "SELECT style_key FROM workbench_brief WHERE id = %s", (brief_id,),
        ).fetchone()
        self.assertEqual(row["style_key"], "ugc")

    def test_submit_pack_with_unknown_style_key_does_not_raise(self):
        """Y03：`submit_pack()` 裡每個 set 的 `style_key` 一樣接了就丟。"""
        pack_id = workbench_repo.submit_pack(web.conn, self.org_id, self.brand_id, {
            "source_kind": "schedule_node", "source_ref": {}, "name": "測試任務包",
            "sets": [{
                "name": "單元 1", "source_ref": {}, "coordinates": {},
                "style_key": "no_such_style", "required_outputs": {"copy": 1},
                "request": {"copy_length": "short"},
            }],
        })
        self.assertIsNotNone(pack_id)

    def test_briefs_with_unknown_style_key_still_write_output_and_leak_nothing(self):
        """Y07／Y09：一份 copy 工單、一份 video_script 工單，事後把儲存的 `style_key` 改成
        非預設值——兩份都照樣寫出結果列（Y07），送給模型的 prompt 也完全沒有「風格：」這個
        殘留欄位（Y09）。"""
        copy_brief_id = self._submit()
        web.conn.execute(
            "UPDATE workbench_brief SET style_key = %s WHERE id = %s",
            ("no_such_style", copy_brief_id),
        )
        video_brief_id = self._submit(
            request={"parts": ["video_script"], "video_script_count": 2},
        )
        web.conn.execute(
            "UPDATE workbench_brief SET style_key = %s WHERE id = %s",
            ("no_such_style", video_brief_id),
        )
        web.conn.commit()

        provider = _SequenceProvider([
            json.dumps(self._copy_reply(), ensure_ascii=False),
            json.dumps({
                "scripts": [_video_script("腳本一"), _video_script("腳本二")],
                "hook_pool": ["hook1", "hook2"], "warnings": [],
            }, ensure_ascii=False),
        ])
        workbench_jobs.PROVIDER = provider
        self._run_worker()

        self.assertEqual(len(self._outputs(copy_brief_id, "copy")), 5)
        self.assertEqual(len(self._outputs(video_brief_id, "video_script")), 2)
        self.assertNotIn("風格：", str(provider.calls))


if __name__ == "__main__":
    unittest.main()
