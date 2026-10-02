"""app/tests/test_workbench_pack_api.py — F02-I03: `/api/workbench/*`'s pack/set surface over
HTTP (`.work/features/F02.md` "API surface"). Fixture shape from `app/tests/test_workbench_api.
py`/`test_schedule.py:626-680` (`TestClient(main.app)`, `_headers(token, org_id)`, each test
module's own fresh `background.app()` needing `register_tasks()` called again). Packs are
seeded directly through `workbench_repo.submit_pack()` (the real upstream door, exercised end
to end in `test_workbench_pack.py`) so these tests only exercise the HTTP/JSON layer this
issue adds; `POST /packs` (自由創作) is the one write path tested over HTTP itself.
"""

import unittest
import uuid

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
import app.workbench as workbench_module
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.identity import repository as identity_repo
from app.workbench import repository as workbench_repo

from .identity_test_helpers import mint_hs256

ACTOR = "測試員"


class _WorkbenchPackApiTestBase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        workbench_module.register_tasks()
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：任務包 API", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        web.conn.commit()

    def _make_org(self, suffix: str) -> tuple:
        org_id = f"org_workbench_pack_api_test_{suffix}"
        web.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (org_id, org_id),
        )
        user_id = uuid.uuid4()
        email = f"workbench-pack-api-test-{suffix}-{user_id.hex[:8]}@example.com"
        identity_repo.create_user(web.conn, user_id, email)
        identity_repo.create_membership(web.conn, org_id, user_id, "owner")
        web.conn.commit()
        token = mint_hs256(sub=str(user_id), email=email)
        return org_id, token

    @staticmethod
    def _headers(token: str, org_id: str) -> dict:
        return {"Authorization": f"Bearer {token}", "X-Org-Id": org_id}

    def _one_set(self, node_key: str, required_outputs: dict, **overrides) -> dict:
        s = {
            "name": f"單元 {node_key}", "source_ref": {"node_key": node_key},
            "coordinates": {}, "style_key": "ugc", "required_outputs": required_outputs,
            "request": {"copy_length": "short", "image_prompt_count": 3},
        }
        s.update(overrides)
        return s

    def _submit_pack(self, sets: list, *, brand_id: str | None = None,
                      org_id: str | None = None, **overrides) -> str:
        pack = {
            "source_kind": "schedule_node",
            "source_ref": {"source_tree_task_id": str(uuid.uuid4())},
            "name": "測試任務包", "summary": {"情境": "測試情境"}, "sets": sets,
        }
        pack.update(overrides)
        return workbench_repo.submit_pack(
            web.conn, org_id or self.org_id, brand_id or self.brand_id, pack,
        )

    def _briefs(self, pack_id: str) -> list:
        rows = web.conn.execute(
            "SELECT * FROM workbench_brief WHERE org_id = %s AND brand_id = %s"
            " AND pack_id = %s ORDER BY created_at",
            (self.org_id, self.brand_id, pack_id),
        ).fetchall()
        return [dict(r) for r in rows]


# -- 案例 1：列表 filters／sorts／q ------------------------------------------------------

class ListPacksTest(_WorkbenchPackApiTestBase):
    def test_status_filter_and_q_and_sort(self):
        pending_id = self._submit_pack([self._one_set("1", {"copy": 1})])
        done_id = self._submit_pack(
            [self._one_set("2", {"copy": 1})],
            name="另一包 咖啡因", summary={"情境": "另一種情境"},
        )
        brief = self._briefs(done_id)[0]
        outputs = workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief["id"],
            part="copy", generation_round=1, body_json=[{"sets": []}],
            coordinates_json=None, llm_task_id=None,
        )
        workbench_repo.select_version(web.conn, self.org_id, self.brand_id, outputs[0]["id"])

        all_resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs")
        self.assertEqual(all_resp.status_code, 200)
        ids = [p["id"] for p in all_resp.json()["packs"]]
        self.assertIn(pending_id, ids)
        self.assertIn(done_id, ids)

        pending_resp = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/packs?status=pending"
        )
        pending_ids = [p["id"] for p in pending_resp.json()["packs"]]
        self.assertIn(pending_id, pending_ids)
        self.assertNotIn(done_id, pending_ids)

        awaiting_resp = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/packs?status=awaiting_approval"
        )
        awaiting_ids = [p["id"] for p in awaiting_resp.json()["packs"]]
        self.assertIn(done_id, awaiting_ids)
        self.assertNotIn(pending_id, awaiting_ids)

        q_resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs?q=咖啡因")
        q_ids = [p["id"] for p in q_resp.json()["packs"]]
        self.assertEqual(q_ids, [done_id])

        sort_resp = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/packs?sort=progress"
        )
        sort_ids = [p["id"] for p in sort_resp.json()["packs"]]
        self.assertEqual(sort_ids[0], done_id)

    def test_status_and_sort_unknown_are_400(self):
        bad_status = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/packs?status=bogus"
        )
        self.assertEqual(bad_status.status_code, 400)
        self.assertEqual(bad_status.json()["error"]["code"], "status_unknown")

        bad_sort = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs?sort=bogus")
        self.assertEqual(bad_sort.status_code, 400)
        self.assertEqual(bad_sort.json()["error"]["code"], "sort_unknown")


# -- 案例 2：另一個組織的 pack／set -> 404 ------------------------------------------------

class CrossTenantTest(_WorkbenchPackApiTestBase):
    def test_other_orgs_pack_and_set_are_404(self):
        org_b, _token_b = self._make_org("cross-tenant")
        brand_b = bi_repo.create_brand(
            web.conn, org_id=org_b, name="測試品牌 B：任務包 API 隔離", client_name=None,
            actor=ACTOR,
        )
        web.conn.commit()
        other_pack_id = self._submit_pack(
            [self._one_set("1", {"copy": 1})], org_id=org_b, brand_id=brand_b["id"],
        )
        other_set_id = [
            dict(r) for r in web.conn.execute(
                "SELECT id FROM workbench_brief WHERE org_id = %s AND pack_id = %s",
                (org_b, other_pack_id),
            ).fetchall()
        ][0]["id"]

        pack_resp = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/packs/{other_pack_id}"
        )
        self.assertEqual(pack_resp.status_code, 404)
        self.assertEqual(pack_resp.json()["error"]["code"], "pack_unknown")

        set_resp = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/sets/{other_set_id}"
        )
        self.assertEqual(set_resp.status_code, 404)
        self.assertEqual(set_resp.json()["error"]["code"], "set_unknown")


# -- 案例 3：select 兩次冪等；核准後 select／run 一律 409 ----------------------------------

class SelectAndLockTest(_WorkbenchPackApiTestBase):
    def test_select_twice_is_idempotent_then_locks_after_approve(self):
        pack_id = self._submit_pack([self._one_set("1", {"copy": 1})])
        brief = self._briefs(pack_id)[0]
        outputs = workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief["id"],
            part="copy", generation_round=1, body_json=[{"sets": []}],
            coordinates_json=None, llm_task_id=None,
        )
        output_id = outputs[0]["id"]
        select_url = (
            f"/api/workbench/brands/{self.brand_id}/sets/{brief['id']}"
            f"/versions/{output_id}/select"
        )
        first = self.client.post(select_url)
        self.assertEqual(first.status_code, 200)
        second = self.client.post(select_url)
        self.assertEqual(second.status_code, 200)

        # 完成三個條件 -> approve
        for key in ("brand_rules_checked", "ready_to_report"):
            resp = self.client.post(
                f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}/completion",
                json={"key": key, "checked": True},
            )
            self.assertEqual(resp.status_code, 200)
        approve_resp = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}/approve"
        )
        self.assertEqual(approve_resp.status_code, 200)
        self.assertEqual(approve_resp.json()["pack"]["status"], "done")

        locked_select = self.client.post(select_url)
        self.assertEqual(locked_select.status_code, 409)
        self.assertEqual(locked_select.json()["error"]["code"], "pack_approved")

        locked_run = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/sets/{brief['id']}/products/copy/run",
            json={},
        )
        self.assertEqual(locked_run.status_code, 409)
        self.assertEqual(locked_run.json()["error"]["code"], "pack_approved")


# -- 案例 4：run 一個已關閉的素材組 -> 409 -------------------------------------------------

class RunClosedSetTest(_WorkbenchPackApiTestBase):
    def test_run_on_closed_set_is_409(self):
        pack_id = self._submit_pack([self._one_set("1", {"copy": 1})])
        brief = self._briefs(pack_id)[0]
        web.conn.execute(
            "UPDATE workbench_brief SET status = 'done', closed_at = now() WHERE id = %s",
            (brief["id"],),
        )
        web.conn.commit()
        resp = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/sets/{brief['id']}/products/copy/run",
            json={},
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["error"]["code"], "brief_closed")


# -- 案例 5：自由創作建 pack -> 命名 自由工作 #2；空 sets／free part 一律 400 -------------------

class CreateFreePackTest(_WorkbenchPackApiTestBase):
    def _body(self, **overrides) -> dict:
        body = {
            "free_text": "五張社群圖片", "style_key": "ugc",
            "sets": [self._one_set("free-1", {"image_prompt": 5})],
        }
        body.update(overrides)
        return body

    def test_second_free_pack_is_named_sequentially(self):
        first = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/packs", json=self._body(),
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()["pack"]["name"], "自由工作 #1")
        self.assertEqual(first.json()["pack"]["source_kind"], "free_job")

        second = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/packs", json=self._body(),
        )
        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.json()["pack"]["name"], "自由工作 #2")

    def test_empty_sets_is_400(self):
        resp = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/packs", json=self._body(sets=[]),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "sets_unknown")

    def test_free_part_in_required_outputs_is_400(self):
        resp = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/packs",
            json=self._body(sets=[self._one_set("free-1", {"free": 1})]),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "part_retired")

    def test_unknown_style_key_top_level_and_per_set_still_creates(self):
        """Y04a／Y04c（F07-I09）：舊全域風格庫退休——`style_key` 不管在 pack 的頂層還是
        單一 set 裡都接了就丟，非預設值「no_such_style」不擋建立。"""
        resp = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/packs",
            json=self._body(
                style_key="no_such_style",
                sets=[self._one_set("free-1", {"image_prompt": 5}, style_key="no_such_style")],
            ),
        )
        self.assertEqual(resp.status_code, 201)

    def test_image_prompt_count_never_defaulted_video_script_count_still_is(self):
        """F07-I14 (Decision 28): `image_prompt` no longer gets an `image_prompt_count`
        default — one round is always 10 — while `video_script_count` still defaults
        from `required_outputs`."""
        resp = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/packs",
            json=self._body(sets=[self._one_set(
                "free-1", {"image_prompt": 5, "video_script": 2},
                request={"copy_length": "short"},
            )]),
        )
        self.assertEqual(resp.status_code, 201)
        pack_id = resp.json()["pack"]["id"]
        brief = self._briefs(pack_id)[0]
        self.assertNotIn("image_prompt_count", brief["request_json"])
        self.assertEqual(brief["request_json"]["video_script_count"], 2)

    def test_context_platform_is_written_and_read_by_both_screens(self):
        """F02-I18 falsifier: `POST /packs` with `context.platform` reaches `PackDetail.meta.
        platform` and, through the set's `chips.platform`, the 生成設定 平台 row's `text` —
        both readers of the one field nobody used to write."""
        created = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/packs",
            json=self._body(context={"platform": "Meta 廣告"}),
        )
        self.assertEqual(created.status_code, 201)
        pack_id = created.json()["pack"]["id"]

        pack_resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}")
        self.assertEqual(pack_resp.json()["pack"]["meta"]["platform"], "Meta 廣告")

        set_id = pack_resp.json()["pack"]["sets"][0]["id"]
        set_resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/sets/{set_id}")
        set_data = set_resp.json()["set"]
        self.assertEqual(set_data["chips"]["platform"], "Meta 廣告")
        settings = {row["label"]: row["text"] for row in set_data["generation_settings"]}
        self.assertEqual(settings["平台"], "Meta 廣告")


# -- 案例 6：一份剛送出的 pack，還沒生成任何版本 -> cell 讀「未生成」 ----------------------------

class FreshPackCellTextTest(_WorkbenchPackApiTestBase):
    def test_fresh_pack_cells_read_未生成(self):
        pack_id = self._submit_pack([self._one_set("1", {"copy": 1, "image_prompt": 1})])
        resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}")
        self.assertEqual(resp.status_code, 200)
        cells = resp.json()["pack"]["sets"][0]["cells"]
        for cell in cells:
            if cell["part"] in ("copy", "image_prompt"):
                self.assertEqual(cell["text"], "未生成")
            else:
                self.assertEqual(cell["text"], "—")


# -- 案例 7：入口 tile 是版本數加總，不是素材組數 ------------------------------------------
# planner review 2026-09-12：一個 set 要 5 張圖時，`counts[]` 要看到 5，不是 1；跟
# `cells[].required` 同一個單位。

class PackCardCountsAreVersionSumsTest(_WorkbenchPackApiTestBase):
    def test_free_job_five_images_reads_0_of_5_not_0_of_1(self):
        pack_id = self._submit_pack([self._one_set("1", {"image_prompt": 5})])
        resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}")
        self.assertEqual(resp.status_code, 200)
        counts = {c["part"]: c for c in resp.json()["pack"]["counts"]}
        self.assertEqual(counts["image_prompt"]["required"], 5)
        self.assertEqual(counts["image_prompt"]["selected"], 0)

    def test_two_sets_each_needing_copy_sum_to_two_required(self):
        pack_id = self._submit_pack([
            self._one_set("1", {"copy": 1}), self._one_set("2", {"copy": 1}),
        ])
        brief = self._briefs(pack_id)[0]
        outputs = workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief["id"],
            part="copy", generation_round=1, body_json=[{"sets": []}],
            coordinates_json=None, llm_task_id=None,
        )
        workbench_repo.select_version(web.conn, self.org_id, self.brand_id, outputs[0]["id"])

        resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}")
        counts = {c["part"]: c for c in resp.json()["pack"]["counts"]}
        self.assertEqual(counts["copy"]["required"], 2)
        self.assertEqual(counts["copy"]["selected"], 1)

        # 素材組層的 cell 跟入口 tile 同一個衍生、同一個單位，不會兜不起來。
        list_resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs")
        card = next(p for p in list_resp.json()["packs"] if p["id"] == pack_id)
        self.assertEqual(card["counts"], resp.json()["pack"]["counts"])


# -- 案例 8：關閉任務包離開入口，但詳情頁仍開得到 --------------------------------------------

class ClosePackLeavesEntranceTest(_WorkbenchPackApiTestBase):
    def test_closed_pack_disappears_from_list_but_detail_still_opens(self):
        pack_id = self._submit_pack([self._one_set("1", {"copy": 1})])
        listed_before = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs")
        self.assertIn(pack_id, [p["id"] for p in listed_before.json()["packs"]])

        close_resp = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}/close"
        )
        self.assertEqual(close_resp.status_code, 200)

        listed_after = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs")
        self.assertNotIn(pack_id, [p["id"] for p in listed_after.json()["packs"]])
        listed_all_status = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/packs?status=all"
        )
        self.assertNotIn(pack_id, [p["id"] for p in listed_all_status.json()["packs"]])

        detail_resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}")
        self.assertEqual(detail_resp.status_code, 200)
        self.assertEqual(detail_resp.json()["pack"]["id"], pack_id)

        # F47 (drill-10 乙 #21): a closed pack stays reachable under 「已關閉」.
        closed = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs?status=closed")
        self.assertEqual(closed.status_code, 200)
        cards = closed.json()["packs"]
        self.assertEqual([p["id"] for p in cards], [pack_id])
        self.assertTrue(cards[0]["closed"])


# -- F47 (drill-10 乙 #17／#19／#20)：查看來源、沒名字的素材組、格式名稱 ------------------------

class CardOriginNamesAndFormatLabelTest(_WorkbenchPackApiTestBase):
    def test_card_carries_origin_href_or_none(self):
        href = f"/brands/{self.brand_id}/ads/campaigns/adc_x"
        with_origin = self._submit_pack(
            [self._one_set("1", {"copy": 1})],
            context={"origin_label": "活動 X", "origin_href": href},
        )
        without = self._submit_pack([self._one_set("2", {"copy": 1})])
        cards = {
            p["id"]: p for p in
            self.client.get(f"/api/workbench/brands/{self.brand_id}/packs").json()["packs"]
        }
        self.assertEqual(cards[with_origin]["origin_href"], href)
        self.assertIsNone(cards[without]["origin_href"])
        self.assertFalse(cards[without]["closed"])

    def test_unnamed_sets_read_as_their_pack(self):
        pack_id = self._submit_pack(
            [self._one_set("1", {"copy": 1}, name=None), self._one_set("2", {"copy": 1}, name="")],
            name="自由工作 #3",
        )
        pack = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}").json()
        self.assertEqual([s["name"] for s in pack["pack"]["sets"]],
                         ["自由工作 #3・第 1 組", "自由工作 #3・第 2 組"])
        brief_id = self._briefs(pack_id)[1]["id"]
        detail = self.client.get(f"/api/workbench/brands/{self.brand_id}/sets/{brief_id}").json()
        self.assertEqual(detail["set"]["name"], "自由工作 #3・第 2 組")
        self.assertEqual([s["name"] for s in detail["set"]["siblings"]],
                         ["自由工作 #3・第 1 組", "自由工作 #3・第 2 組"])

    def test_header_shows_the_format_label_not_the_key(self):
        # The vocabulary is seeded through the brand-library door (schedule owns the table).
        listed = self.client.get(f"/api/schedule/brands/{self.brand_id}/coordinates")
        self.assertEqual(listed.status_code, 200, listed.text)
        rows = listed.json()["coordinates"]
        label = next(r["label"] for r in rows
                     if r["dimension"] == "format" and r["key"] == "single_image")
        pack_id = self._submit_pack([
            self._one_set("1", {"copy": 1}, coordinates={"format": "single_image"}),
            self._one_set("2", {"copy": 1}, coordinates={"format": "1:1"}),
        ])
        briefs = self._briefs(pack_id)
        sizes = [
            self.client.get(f"/api/workbench/brands/{self.brand_id}/sets/{b['id']}")
            .json()["set"]["chips"]["size"]
            for b in briefs
        ]
        self.assertEqual(sizes, [label, "1:1"])
        self.assertNotEqual(label, "single_image")


# -- 案例 9：select 一個不屬於這個 set 的 version_id -> 404，且不寫入 ---------------------------

class SelectMismatchedSetIs404WithoutWriteTest(_WorkbenchPackApiTestBase):
    def test_select_version_from_another_set_is_404_and_does_not_adopt(self):
        pack_id = self._submit_pack([
            self._one_set("1", {"copy": 1}), self._one_set("2", {"copy": 1}),
        ])
        briefs = self._briefs(pack_id)
        set_a, set_b = briefs[0], briefs[1]
        outputs_a = workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=set_a["id"],
            part="copy", generation_round=1, body_json=[{"sets": []}],
            coordinates_json=None, llm_task_id=None,
        )
        output_a_id = outputs_a[0]["id"]

        # 拿 set A 的 version_id，打在 set B 的 URL 上。
        mismatched_url = (
            f"/api/workbench/brands/{self.brand_id}/sets/{set_b['id']}"
            f"/versions/{output_a_id}/select"
        )
        resp = self.client.post(mismatched_url)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["error"]["code"], "output_unknown")

        row = web.conn.execute(
            "SELECT adopted_at FROM workbench_output WHERE id = %s", (output_a_id,),
        ).fetchone()
        self.assertIsNone(row["adopted_at"])


# -- 案例 10：image_prompt 一輪 10 版（§5.8 shape）：卡片／複製全部／② 變體 ------------------
# F07-I08.

def _image_fingerprint(*, slot="exploit", slot_label="主力"):
    return {
        "image_task": {"key": "convert", "label": "讓猶豫的人下單"},
        "device": {"key": "contrast", "label": "對照"},
        "layout": {"key": "candid_scene", "label": "情境畫面"},
        "look": {"key": "phone_raw", "label": "手機原生抓拍"},
        "subject_role": {"key": "hero", "label": "主角"},
        "persuasion": {"key": "none", "label": "無"},
        "slot": {"key": slot, "label": slot_label},
    }


def _image_round(*, recommended_index=1):
    return {
        "format": "single_image", "audience_key": "warm_engaged", "image_task": "convert",
        "identity_id": "wvi_1", "identity_text": "品牌識別文字",
        "plan": [{"look": "phone_raw", "slot": "exploit"}] * 10,
        "look_order": {"exploit": ["phone_raw"], "explore": []},
        "recommended_index": recommended_index, "recommended_slot": "exploit",
        "learning_ids": [],
    }


def _image_body(i: int, **overrides) -> dict:
    prompt = f"這是第 {i} 則畫面描述，「主標{i}」放在畫面上方。"
    body = {
        "title": f"點子{i}", "headline": f"主標{i}",
        "prompt": prompt, "text": f"{prompt}\n\n品牌視覺規範：X\n風格規範：Y",
        "fingerprint": _image_fingerprint(), "cards": None, "round": _image_round(),
        "validation": [], "warnings": [],
    }
    body.update(overrides)
    return body


class ImagePromptRoundApiTest(_WorkbenchPackApiTestBase):
    def test_ten_row_round_has_badges_copy_all_text_and_variant_on_selected(self):
        pack_id = self._submit_pack([{
            "name": "單元 1", "source_ref": {"node_key": "1"}, "coordinates": {},
            "style_key": "ugc", "required_outputs": {"image_prompt": 1},
            "request": {"variant_count": 6},
        }])
        brief = self._briefs(pack_id)[0]
        outputs = workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief["id"],
            part="image_prompt", generation_round=1,
            body_json=[_image_body(i) for i in range(1, 11)],
            coordinates_json=None, llm_task_id=None,
        )
        workbench_repo.select_version(web.conn, self.org_id, self.brand_id, outputs[0]["id"])

        resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/sets/{brief['id']}")
        self.assertEqual(resp.status_code, 200)
        image_product = resp.json()["set"]["products"]["image_prompt"]
        versions = image_product["versions"]
        self.assertEqual(len(versions), 10)
        for version in versions:
            self.assertEqual(version["badges"][0], "主力")
            selected = version["version_index"] == 1
            expected_cards = 2 if selected else 1
            self.assertEqual(len(version["prompt_cards"]), expected_cards)
            if selected:
                self.assertEqual(version["prompt_cards"][1]["label"], "② 變體")

        copy_all_text = image_product["copy_all_text"]
        assert copy_all_text is not None
        self.assertTrue(copy_all_text.startswith("請一次生成 10 張圖，每張只照下面對應的那一段"))
        for i in range(1, 11):
            self.assertIn(f"第 {i} 張\n{_image_body(i)['text']}", copy_all_text)

    def test_copy_all_text_reads_only_the_max_round(self):
        # A07: seeding two 10-row rounds must not double the blocks.
        pack_id = self._submit_pack([{
            "name": "單元 A07", "source_ref": {"node_key": "a07"}, "coordinates": {},
            "style_key": "ugc", "required_outputs": {"image_prompt": 1},
            "request": {},
        }])
        def _round_body(i: int, tag: str) -> dict:
            prompt = f"這是第 {i} 則畫面描述（{tag}），「主標{i}」放在畫面上方。"
            return _image_body(i, prompt=prompt, text=f"{prompt}\n\n品牌視覺規範：X\n風格規範：Y")

        brief = self._briefs(pack_id)[0]
        workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief["id"],
            part="image_prompt", generation_round=1,
            body_json=[_round_body(i, "舊輪") for i in range(1, 11)],
            coordinates_json=None, llm_task_id=None,
        )
        workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief["id"],
            part="image_prompt", generation_round=2,
            body_json=[_round_body(i, "新輪") for i in range(1, 11)],
            coordinates_json=None, llm_task_id=None,
        )
        resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/sets/{brief['id']}")
        copy_all_text = resp.json()["set"]["products"]["image_prompt"]["copy_all_text"]
        assert copy_all_text is not None
        self.assertEqual(copy_all_text.count("第 1 張"), 1)
        self.assertNotIn("舊輪", copy_all_text)
        self.assertIn("新輪", copy_all_text)


# -- 案例 11：pack 的探索風格佔比提醒 -----------------------------------------------------
# F07-I08 (ARCHITECTURE.md §5.9 Decision 29).

class ImageExplorationWarningTest(_WorkbenchPackApiTestBase):
    def _pack_with_adopted_slots(self, slots: list[str]) -> str:
        sets = [self._one_set(str(i), {"image_prompt": 1}) for i in range(len(slots))]
        pack_id = self._submit_pack(sets)
        for brief, slot in zip(self._briefs(pack_id), slots, strict=True):
            outputs = workbench_repo.write_output(
                web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief["id"],
                part="image_prompt", generation_round=1,
                body_json=[_image_body(1, fingerprint=_image_fingerprint(
                    slot=slot, slot_label="探索" if slot == "explore" else "主力",
                ))],
                coordinates_json=None, llm_task_id=None,
            )
            workbench_repo.select_version(web.conn, self.org_id, self.brand_id, outputs[0]["id"])
        return pack_id

    def test_all_exploit_gives_warning_and_does_not_touch_can_approve(self):
        # W07b: the warning must not leak into `blocking_text` — compare against a pack in
        # the same completion state (all 4 sets adopted) that has no warning.
        pack_id = self._pack_with_adopted_slots(["exploit"] * 4)
        resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}")
        pack = resp.json()["pack"]
        self.assertEqual(
            pack["image_exploration_warning"],
            "這包選定的圖裡，探索風格只有 0／4 張（少於三成），新風格很難被測到。"
            "可以在標著「建議選這張」的探索圖改選。",
        )
        self.assertIsInstance(pack["can_approve"], bool)  # this field never touches it

        no_warning_pack_id = self._pack_with_adopted_slots(
            ["explore", "explore", "exploit", "exploit"]
        )
        no_warning_resp = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/packs/{no_warning_pack_id}"
        )
        no_warning_pack = no_warning_resp.json()["pack"]
        self.assertIsNone(no_warning_pack["image_exploration_warning"])
        self.assertEqual(pack["blocking_text"], no_warning_pack["blocking_text"])
        self.assertNotIn("探索風格", pack["blocking_text"])

    def test_two_of_four_explore_is_none(self):
        pack_id = self._pack_with_adopted_slots(["explore", "explore", "exploit", "exploit"])
        resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}")
        pack = resp.json()["pack"]
        self.assertIn("image_exploration_warning", pack)  # W06: key always present
        self.assertIsNone(pack["image_exploration_warning"])

    def test_one_of_four_explore_still_warns(self):
        # W04: 1/4 = 25% < 30% must still warn.
        pack_id = self._pack_with_adopted_slots(["explore", "exploit", "exploit", "exploit"])
        resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}")
        self.assertIsNotNone(resp.json()["pack"]["image_exploration_warning"])

    def test_unadopted_explore_row_does_not_count(self):
        # W02: M/N only count `is_adopted` rows — an unselected explore row in the same pack
        # as 4 adopted-exploit sets must not move the ratio.
        sets = [self._one_set(str(i), {"image_prompt": 1}) for i in range(5)]
        pack_id = self._submit_pack(sets)
        briefs = self._briefs(pack_id)
        for brief in briefs[:4]:
            outputs = workbench_repo.write_output(
                web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief["id"],
                part="image_prompt", generation_round=1,
                body_json=[_image_body(1, fingerprint=_image_fingerprint(slot="exploit"))],
                coordinates_json=None, llm_task_id=None,
            )
            workbench_repo.select_version(web.conn, self.org_id, self.brand_id, outputs[0]["id"])
        workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=briefs[4]["id"],
            part="image_prompt", generation_round=1,
            body_json=[_image_body(1, fingerprint=_image_fingerprint(
                slot="explore", slot_label="探索",
            ))],
            coordinates_json=None, llm_task_id=None,
        )
        # not selected — stays unadopted.
        resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}")
        self.assertEqual(
            resp.json()["pack"]["image_exploration_warning"],
            "這包選定的圖裡，探索風格只有 0／4 張（少於三成），新風格很難被測到。"
            "可以在標著「建議選這張」的探索圖改選。",
        )

    def test_adopted_pre_f07_row_does_not_count(self):
        # W03: M only counts rows carrying `fingerprint.slot` — a pre-F07 adopted row
        # elsewhere in the pack must not raise M.
        sets = [self._one_set(str(i), {"image_prompt": 1}) for i in range(5)]
        pack_id = self._submit_pack(sets)
        briefs = self._briefs(pack_id)
        for brief in briefs[:4]:
            outputs = workbench_repo.write_output(
                web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief["id"],
                part="image_prompt", generation_round=1,
                body_json=[_image_body(1, fingerprint=_image_fingerprint(slot="exploit"))],
                coordinates_json=None, llm_task_id=None,
            )
            workbench_repo.select_version(web.conn, self.org_id, self.brand_id, outputs[0]["id"])
        pre_f07_outputs = workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=briefs[4]["id"],
            part="image_prompt", generation_round=1,
            body_json=[{"mode": "variant", "rendered": {"hero": "x", "variant": "y"}}],
            coordinates_json=None, llm_task_id=None,
        )
        workbench_repo.select_version(
            web.conn, self.org_id, self.brand_id, pre_f07_outputs[0]["id"],
        )
        resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}")
        self.assertEqual(
            resp.json()["pack"]["image_exploration_warning"],
            "這包選定的圖裡，探索風格只有 0／4 張（少於三成），新風格很難被測到。"
            "可以在標著「建議選這張」的探索圖改選。",
        )

    def test_exactly_30_percent_does_not_warn_but_20_percent_does(self):
        # W05: strict `<`, not `<=` — exactly 3 of 10 (30%) must not warn; 2 of 10 (20%) must.
        exact_30 = self._pack_with_adopted_slots(["explore"] * 3 + ["exploit"] * 7)
        resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs/{exact_30}")
        self.assertIsNone(resp.json()["pack"]["image_exploration_warning"])

        below_30 = self._pack_with_adopted_slots(["explore"] * 2 + ["exploit"] * 8)
        resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs/{below_30}")
        self.assertIsNotNone(resp.json()["pack"]["image_exploration_warning"])

    def test_warning_never_blocks_approval(self):
        # W07: a pack with the warning still approves once its own completion conditions
        # are met.
        pack_id = self._pack_with_adopted_slots(["exploit"] * 4)
        resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}")
        self.assertIsNotNone(resp.json()["pack"]["image_exploration_warning"])
        for key in ("brand_rules_checked", "ready_to_report"):
            comp = self.client.post(
                f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}/completion",
                json={"key": key, "checked": True},
            )
            self.assertEqual(comp.status_code, 200)
        pre_approve = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}")
        self.assertIs(pre_approve.json()["pack"]["can_approve"], True)
        approve = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}/approve"
        )
        self.assertEqual(approve.status_code, 200)


# -- 案例 12：GET /visual-spec 品牌事實負面用語警告 -----------------------------------------
# F07-I08 (ARCHITECTURE.md §5.9 Decision 24).

class VisualSpecWarningTest(_WorkbenchPackApiTestBase):
    def test_three_negatives_give_one_warning(self):
        bi_repo.create_brand_fact(
            web.conn, self.brand_id, actor=ACTOR, fact_type="visual_base",
            label="視覺基礎", value="不要出現競品\n避免使用紅色\n禁止出現真人",
            status="confirmed", confirmed_by=ACTOR,
        )
        web.conn.commit()
        resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/visual-spec")
        self.assertEqual(resp.status_code, 200)
        warnings = resp.json()["warnings"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("3 句", warnings[0]["text"])
        self.assertEqual(warnings[0]["href"], f"/brands/{self.brand_id}/library?tab=facts")

    def test_other_orgs_brand_is_404(self):
        org_b, _token_b = self._make_org("visual-spec")
        brand_b = bi_repo.create_brand(
            web.conn, org_id=org_b, name="測試品牌 B：視覺基礎隔離", client_name=None,
            actor=ACTOR,
        )
        web.conn.commit()
        resp = self.client.get(f"/api/workbench/brands/{brand_b['id']}/visual-spec")
        self.assertEqual(resp.status_code, 404)

    def test_exactly_two_negatives_gives_no_warning(self):
        # G04: `<= 2` must not warn.
        bi_repo.create_brand_fact(
            web.conn, self.brand_id, actor=ACTOR, fact_type="visual_base",
            label="視覺基礎", value="不要出現競品\n避免使用紅色",
            status="confirmed", confirmed_by=ACTOR,
        )
        web.conn.commit()
        resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/visual-spec")
        self.assertEqual(resp.json()["warnings"], [])

    def test_pending_fact_is_not_counted(self):
        # G03: only confirmed facts feed `brand_spec_text` — a pending fact with three
        # negatives must not warn.
        bi_repo.create_brand_fact(
            web.conn, self.brand_id, actor=ACTOR, fact_type="visual_base",
            label="視覺基礎", value="不要出現競品\n避免使用紅色\n禁止出現真人",
            status="pending",
        )
        web.conn.commit()
        resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/visual-spec")
        self.assertEqual(resp.json()["warnings"], [])


if __name__ == "__main__":
    unittest.main()


# -- F34-I02（Contract S）：版本列表帶 statutory_warning，只提醒不擋 ----------------------------

_ROUND = {"sets": [{"body": "十分鐘內治療你的午後疲勞"},
                   {"body": "幫助你把下午撐完，精神旺盛到下班"}]}


class StatutoryWarningTest(_WorkbenchPackApiTestBase):
    def test_food_tw_brand_lists_statutory_warning_beside_claim_warning(self):
        bi_repo.set_regulatory_regime(web.conn, self.brand_id, "food_tw", actor=ACTOR)
        pack = self._submit_pack([self._one_set("1", {"copy": 1})])
        brief = self._briefs(pack)[0]
        workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief["id"],
            part="copy", generation_round=1,
            body_json=[_ROUND, _ROUND],
            coordinates_json=None, llm_task_id=None,
        )
        versions = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/sets/{brief['id']}"
        ).json()["set"]["products"]["copy"]["versions"]
        by_index = {v["version_index"]: v for v in versions}
        warning = by_index[1]["statutory_warning"]
        assert warning["terms"] == [{"term": "治療", "tier_label": "醫療效能"}]
        assert warning["sentence"] == "食品廣告通常不能這樣講（食安法第 28 條）。確認無誤仍可選定。"
        assert warning["href"] == "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0040140"
        assert by_index[1]["claim_warning"] is None
        assert by_index[2]["statutory_warning"] is None

    def test_brand_without_regime_lists_none(self):
        pack = self._submit_pack([self._one_set("1", {"copy": 1})])
        brief = self._briefs(pack)[0]
        workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief["id"],
            part="copy", generation_round=1,
            body_json=[{"sets": [{"body": "十分鐘內治療你的午後疲勞"}]}],
            coordinates_json=None, llm_task_id=None,
        )
        versions = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/sets/{brief['id']}"
        ).json()["set"]["products"]["copy"]["versions"]
        assert versions[0]["statutory_warning"] is None
        result = workbench_module.validate_claims(
            web.conn, self.org_id, self.brand_id, None, {"body": "治療"},
        )
        assert result["statutory_hits"] == [] and result["statutory_warning"] is None


# -- 案例 14：`blocking_text` 逐項點名（F40-I05，drill-7 #14 站 18c）---------------------------
# 「核准整包」灰掉時後端必須說出每一個原因：素材組沒做完照舊，完成條件沒勾的按標籤列出；
# 三項都 ok 時為空字串。

class BlockingTextNamesEveryReasonTest(_WorkbenchPackApiTestBase):
    def _pack_with_all_sets_done(self) -> str:
        pack_id = self._submit_pack([self._one_set("1", {"copy": 1})])
        brief = self._briefs(pack_id)[0]
        outputs = workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief["id"],
            part="copy", generation_round=1, body_json=[{"sets": []}],
            coordinates_json=None, llm_task_id=None,
        )
        workbench_repo.select_version(web.conn, self.org_id, self.brand_id, outputs[0]["id"])
        return pack_id

    def _tick(self, pack_id: str, key: str) -> None:
        resp = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}/completion",
            json={"key": key, "checked": True},
        )
        self.assertEqual(resp.status_code, 200)

    def _pack(self, pack_id: str) -> dict:
        resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}")
        self.assertEqual(resp.status_code, 200)
        return resp.json()["pack"]

    def test_sets_done_but_one_box_unticked_names_that_box(self):
        pack_id = self._pack_with_all_sets_done()
        self._tick(pack_id, "brand_rules_checked")
        pack = self._pack(pack_id)
        self.assertIs(pack["can_approve"], False)
        self.assertEqual(pack["blocking_text"], "還沒勾「可核准整包並回報上游」")

    def test_sets_done_and_both_boxes_unticked_names_both(self):
        pack = self._pack(self._pack_with_all_sets_done())
        self.assertIs(pack["can_approve"], False)
        self.assertEqual(
            pack["blocking_text"], "還沒勾「確認內容符合品牌規範」「可核准整包並回報上游」",
        )
        self.assertNotIn("素材組未完成", pack["blocking_text"])

    def test_missing_sets_and_unticked_boxes_are_joined(self):
        pack = self._pack(self._submit_pack([self._one_set("1", {"copy": 1})]))
        self.assertIs(pack["can_approve"], False)
        self.assertEqual(
            pack["blocking_text"],
            "尚有 1 個素材組未完成；還沒勾「確認內容符合品牌規範」「可核准整包並回報上游」",
        )
        # The missing-set sentence already covers `required_outputs_met`; it is not repeated.
        self.assertNotIn("完成所有素材組", pack["blocking_text"])

    def test_all_ticked_is_empty(self):
        pack_id = self._pack_with_all_sets_done()
        for key in ("brand_rules_checked", "ready_to_report"):
            self._tick(pack_id, key)
        pack = self._pack(pack_id)
        self.assertIs(pack["can_approve"], True)
        self.assertEqual(pack["blocking_text"], "")
