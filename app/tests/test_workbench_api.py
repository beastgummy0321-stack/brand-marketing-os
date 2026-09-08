"""app/tests/test_workbench_api.py — ticket workbench/03: `/api/workbench/*` over HTTP
(`docs/issues/workbench/03-workbench-routes-and-api-types.md` "How we know it's done" #2).

Fixture shape from `app/tests/test_schedule.py:626-680` (`TestClient(main.app)`,
`_headers(token, org_id)`, each test module's own fresh `background.app()` needing
`register_tasks()` called again — see that file's own comment for why). FakeProvider only,
no real network request (same rule as `test_workbench.py`). Six cases, matching the ticket's
own numbering: (1) create + default/closed list filters; (2) create-time 400s; (3) run-part
400/409s; (4) FakeProvider round-trip through the worker, adopt, second round; (5) cross-tenant
404 `brief_unknown` on GET/run/adopt/close/DELETE; (6) delete cascades outputs.
"""

import json
import unittest
import uuid

from fastapi.testclient import TestClient

import app.background as background_module
import app.main as main
import app.schedule as schedule_module
import app.shared.web as web
import app.workbench as workbench_module
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.identity import repository as identity_repo
from app.llm import providers
from app.schedule import repository as schedule_repo
from app.workbench import jobs as workbench_jobs
from app.workbench import prompts as workbench_prompts
from app.workbench import repository as workbench_repo

from .identity_test_helpers import mint_hs256

ACTOR = "測試員"


def _cjk(n: int) -> str:
    """n 個中文字（不含換行）——比照 `test_workbench.py` 同名函式，灌出剛好落在某個
    字數帶的假文案，不必手動數字數。"""
    base = "測試文案內容真實好用推薦體驗品質細節故事風格"
    return (base * (n // len(base) + 1))[:n]


def _fake(rendered_output: str) -> providers.FakeProvider:
    return providers.FakeProvider(response=providers.ProviderResponse(
        output_text=rendered_output, structured=None,
        usage=providers.Usage(input_tokens=500, output_tokens=200), stop_reason="end_turn",
    ))


class _WorkbenchApiTestBase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        # DSN 換了要重掛（每個測試模組自己的 schema）——同一個理由，`app/workbench/
        # jobs.py register_tasks()` 檔頭跟 `app/schedule/jobs.py` 一樣講過。這支測試檔
        # 只打 workbench 的端點，掛 schedule 的純粹是比照 `test_schedule.py:626-680`
        # 那份 fixture 形狀，兩邊互不干擾（idempotent）。
        schedule_module.register_tasks()
        workbench_module.register_tasks()
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：工作檯 API", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        self.product = bi_repo.create_product(
            web.conn, self.brand_id, name="測試產品：工作檯 API", actor=ACTOR,
        )
        web.conn.commit()
        self._orig_provider = workbench_jobs.PROVIDER

    def tearDown(self):
        workbench_jobs.PROVIDER = self._orig_provider

    def _run_worker(self) -> None:
        web.conn.commit()
        background_module.app().run_worker(wait=False)

    def _make_org(self, suffix: str) -> tuple:
        org_id = f"org_workbench_api_test_{suffix}"
        web.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (org_id, org_id),
        )
        user_id = uuid.uuid4()
        email = f"workbench-api-test-{suffix}-{user_id.hex[:8]}@example.com"
        identity_repo.create_user(web.conn, user_id, email)
        identity_repo.create_membership(web.conn, org_id, user_id, "owner")
        web.conn.commit()
        token = mint_hs256(sub=str(user_id), email=email)
        return org_id, token

    @staticmethod
    def _headers(token: str, org_id: str) -> dict:
        return {"Authorization": f"Bearer {token}", "X-Org-Id": org_id}

    def _new_brief_body(self, **overrides) -> dict:
        body = {
            "kind": "copy", "product_id": self.product["id"], "coordinates": None,
            "visual_tone": None, "visual_concept": None, "style_key": "ugc",
            "request": {"use_brand_knowledge": False, "free_text": None,
                        "image_prompt_count": None, "on_image_texts": None},
        }
        body.update(overrides)
        return body

    def _create(self, brand_id: str | None = None, **overrides):
        return self.client.post(
            f"/api/workbench/brands/{brand_id or self.brand_id}/briefs",
            json=self._new_brief_body(**overrides),
        )


# -- 案例 1：手動 copy 工單 -> 201／queued；預設列表看得到；status=closed 濾掉 -----------

class CreateAndListBriefsTest(_WorkbenchApiTestBase):
    def test_create_then_default_and_closed_filters(self):
        resp = self._create(kind="copy")
        self.assertEqual(resp.status_code, 201)
        brief = resp.json()["brief"]
        self.assertEqual(brief["status"], "queued")
        brief_id = brief["id"]

        count = web.conn.execute(
            "SELECT count(*) AS n FROM workbench_brief WHERE id = %s", (brief_id,)
        ).fetchone()["n"]
        self.assertEqual(count, 1)

        listed = self.client.get(f"/api/workbench/brands/{self.brand_id}/briefs")
        self.assertEqual(listed.status_code, 200)
        self.assertIn(brief_id, [b["id"] for b in listed.json()["briefs"]])

        closed = self.client.get(f"/api/workbench/brands/{self.brand_id}/briefs?status=closed")
        self.assertEqual(closed.status_code, 200)
        self.assertNotIn(brief_id, [b["id"] for b in closed.json()["briefs"]])


# -- 案例 2：送出時的四種 400 -----------------------------------------------------------

class CreateBriefValidationTest(_WorkbenchApiTestBase):
    def test_unknown_style_key_is_style_unknown(self):
        resp = self._create(style_key="studio")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "style_unknown")

    def test_ad_creative_kind_is_kind_unknown(self):
        resp = self._create(kind="ad_creative")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "kind_unknown")

    def test_image_prompt_without_on_image_texts_is_rejected(self):
        resp = self._create(kind="image_prompt")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "on_image_texts_required")

    def test_status_unknown_on_list(self):
        resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/briefs?status=bogus")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "status_unknown")


# -- 案例 3：run image_prompt 的四種張數／狀態錯誤 ---------------------------------------

class RunPartValidationTest(_WorkbenchApiTestBase):
    def _image_prompt_brief(self, *, status: str = "done") -> str:
        """票 02 的 `submit_brief()` INSERT 一律寫 `status='queued'`（不管
        `_parts_for()` 有沒有真的排東西）——這支工單沒給 `image_prompt_count`，不會有
        worker 幫它翻到別的狀態，所以這裡用一行 UPDATE 模擬「送出那一輪已經跑完」，
        才測得到 count/closed 這幾條（`status` 卡在 queued/running 會先被
        `round_running` 擋下，那是另一個案例）。"""
        resp = self._create(
            kind="image_prompt",
            request={"use_brand_knowledge": False, "free_text": None,
                     "image_prompt_count": None, "on_image_texts": ["一杯搞定早餐"]},
        )
        self.assertEqual(resp.status_code, 201)
        brief_id = resp.json()["brief"]["id"]
        web.conn.execute(
            "UPDATE workbench_brief SET status = %s WHERE id = %s", (status, brief_id)
        )
        web.conn.commit()
        return brief_id

    def _run(self, brief_id: str, count) -> dict:
        return self.client.post(
            f"/api/workbench/brands/{self.brand_id}/briefs/{brief_id}/parts/image_prompt/run",
            json={"count": count},
        )

    def test_count_zero_is_out_of_range(self):
        brief_id = self._image_prompt_brief()
        resp = self._run(brief_id, 0)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "count_out_of_range")

    def test_count_31_is_out_of_range(self):
        brief_id = self._image_prompt_brief()
        resp = self._run(brief_id, 31)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "count_out_of_range")

    def test_closed_brief_is_409(self):
        brief_id = self._image_prompt_brief()
        close_resp = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/briefs/{brief_id}/close"
        )
        self.assertEqual(close_resp.status_code, 200)
        resp = self._run(brief_id, 3)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["error"]["code"], "brief_closed")

    def test_running_brief_is_409(self):
        brief_id = self._image_prompt_brief(status="running")
        resp = self._run(brief_id, 3)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["error"]["code"], "round_running")


# -- 案例 4：FakeProvider 跑過 worker -> 輸出列 -> 採用 -> 第二輪不動採用 ------------------

class RoundTripAdoptionTest(_WorkbenchApiTestBase):
    def _copy_reply(self) -> str:
        coordinate_rows = schedule_repo.list_coordinates(web.conn, self.org_id, self.brand_id)
        coordinates = {
            dim: next(r["label"] for r in coordinate_rows if r["dimension"] == dim)
            for dim in workbench_prompts.COORDINATE_KEYS
        }
        return json.dumps({
            "coordinates": coordinates,
            "short": [_cjk(140) for _ in range(5)],
            "medium": [_cjk(450) for _ in range(3)],
            "long": [_cjk(950) for _ in range(2)],
            "headlines": [_cjk(10) for _ in range(5)],
            "descriptions": [_cjk(15) for _ in range(5)],
            "warnings": [],
        }, ensure_ascii=False)

    def test_run_output_adopt_then_second_round_keeps_adoption(self):
        create_resp = self._create(kind="copy")
        self.assertEqual(create_resp.status_code, 201)
        brief_id = create_resp.json()["brief"]["id"]

        reply = self._copy_reply()
        workbench_jobs.PROVIDER = _fake(reply)
        self._run_worker()

        detail = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/briefs/{brief_id}"
        ).json()["brief"]
        self.assertEqual(len(detail["outputs"]), 1)
        output_id = detail["outputs"][0]["id"]

        adopt_resp = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/briefs/{brief_id}/outputs/{output_id}/adopt"
        )
        self.assertEqual(adopt_resp.status_code, 200)
        self.assertEqual(adopt_resp.json()["brief"]["parts"]["copy"]["adopted_round"], 1)

        run_resp = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/briefs/{brief_id}/parts/copy/run", json={},
        )
        self.assertEqual(run_resp.status_code, 200)

        workbench_jobs.PROVIDER = _fake(reply)
        self._run_worker()

        final = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/briefs/{brief_id}"
        ).json()["brief"]
        self.assertEqual(final["parts"]["copy"]["latest_round"], 2)
        self.assertEqual(final["parts"]["copy"]["adopted_round"], 1)


# -- 案例 5：跨租戶——org A 自己的 brand，org B 的 brief id -> 五支都 404 brief_unknown ----

class CrossTenantTest(_WorkbenchApiTestBase):
    def test_other_orgs_brief_id_is_brief_unknown_everywhere(self):
        org_b, token_b = self._make_org("cross-tenant")
        brand_b = bi_repo.create_brand(
            web.conn, org_id=org_b, name="測試品牌 B：工作檯 API 隔離", client_name=None,
            actor=ACTOR,
        )
        web.conn.commit()
        create_resp = self.client.post(
            f"/api/workbench/brands/{brand_b['id']}/briefs",
            json=self._new_brief_body(product_id=None),
            headers=self._headers(token_b, org_b),
        )
        self.assertEqual(create_resp.status_code, 201)
        other_brief_id = create_resp.json()["brief"]["id"]

        get_resp = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/briefs/{other_brief_id}"
        )
        self.assertEqual(get_resp.status_code, 404)
        self.assertEqual(get_resp.json()["error"]["code"], "brief_unknown")

        run_resp = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/briefs/{other_brief_id}/parts/copy/run",
            json={},
        )
        self.assertEqual(run_resp.status_code, 404)
        self.assertEqual(run_resp.json()["error"]["code"], "brief_unknown")

        adopt_resp = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/briefs/{other_brief_id}"
            "/outputs/wbo_does_not_exist/adopt"
        )
        self.assertEqual(adopt_resp.status_code, 404)
        self.assertEqual(adopt_resp.json()["error"]["code"], "brief_unknown")

        close_resp = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/briefs/{other_brief_id}/close"
        )
        self.assertEqual(close_resp.status_code, 404)
        self.assertEqual(close_resp.json()["error"]["code"], "brief_unknown")

        delete_resp = self.client.delete(
            f"/api/workbench/brands/{self.brand_id}/briefs/{other_brief_id}"
        )
        self.assertEqual(delete_resp.status_code, 404)
        self.assertEqual(delete_resp.json()["error"]["code"], "brief_unknown")


# -- 案例 6：DELETE -> 204，outputs 跟著清空 ---------------------------------------------

class DeleteBriefTest(_WorkbenchApiTestBase):
    def test_delete_cascades_outputs(self):
        create_resp = self._create(kind="copy")
        brief_id = create_resp.json()["brief"]["id"]
        workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief_id,
            part="copy", generation_round=1, body_json={"headlines": []},
            coordinates_json=None, llm_task_id=None,
        )
        delete_resp = self.client.delete(
            f"/api/workbench/brands/{self.brand_id}/briefs/{brief_id}"
        )
        self.assertEqual(delete_resp.status_code, 204)
        count = web.conn.execute(
            "SELECT count(*) AS n FROM workbench_output WHERE brief_id = %s", (brief_id,)
        ).fetchone()["n"]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
