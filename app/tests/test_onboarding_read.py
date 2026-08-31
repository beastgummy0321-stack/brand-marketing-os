"""app/tests/test_onboarding_read.py — 票 S2「開帳讀歷史」：讀一個廣告帳戶過去在 Meta 上
投過什麼、逐活動各跑一個分析師，交人手動勾選要不要把結論存進學習帳本。

只寫 docs/workflow-diet.md 第 4 條允許的四類（S2-DESIGN.md D15 逐一點名），每支測試的
docstring 都寫死是哪一類：

1. 資料正確性——生成不寫帳本：跑完一次讀取、不勾選任何結論，`learning_ledger` 一列都不該
   多出來，結論仍然讀得回來。
2. 資料正確性——逐條接受：勾一條只多一列且是被勾的那條；全選補齊其餘；載入時沒有任何一條
   預先打勾；`source_track` 標成 imported（票 S2 done-check 2／3 併成一支，不重複驗兩遍）。
3. 金額——兩個活動平行成功：ADR 0042 修正版點名的那支測試，鎖字面值是
   `onboarding_read:{account}:{campaign}`，抓太寬會拒收第二個活動（錢照花、帳查不到），
   抓太窄會讓同一份工作被算兩次錢。
4. 資料正確性——fan-in 計數：一個活動故意失敗，「全部完成」該是 False；只重跑那一個活動
   之後變 True，另一個活動不會跟著多跑一次。
5. 資料正確性——回不出素材的廣告要被點名，不能整筆消失。
6. 資料正確性——Meta 列得出來、但這段期間手上沒有數字的活動不派分析師（派了只會拿到空
   CSV、生出無中生有的結論），但一定要被點名；2026-08-31 實機驗收量到真帳號 58 個活動裡
   34 個屬於這類，靜靜跳過等於謊報這次讀了整個帳號。
7. 資料正確性——組出來的 prompt 真的貼進了 ab-testing.md 第 3 節樣本數速查表逐字內容跟
   部門任務檔識別行，這是模型真正需要的判斷依據有沒有到位，取代已刪掉的「grep diff 找
   常數」檢查。

畫面行為不寫在這裡，只留 `frontend/e2e/smoke.spec.ts` 一支端到端煙霧測試
（S2-DESIGN.md D0-b：那支證明路由掛上了、API 答得出來、誠實的空狀態畫得出來——「勾一條
→ 剛好一列且是被勾的那條」這件事由本檔的測試 2 這條走真實 HTTP 路徑的後端測試證明，
e2e 那支只驗新帳號沒有 Meta 帳號時的空狀態）。

換掉 `app.meta.graph.list_entities`／`list_ad_creatives` 而不是既有的 `graph.fetch_page`
（test_meta_daily_spend.py 那個替身管的是 insights 端點的分頁與編碼，跟這裡新加的物件
端點是完全不同的呼叫）：這批測試要驗的是 `app/schedule/onboarding.py` 自己的邏輯，不是
D5 的分頁或 `effective_status` 編碼——那些沒有機器檢查，是這次交付的已知落差之一
（見報告 unsettled）。`onboarding.PROVIDER` 的換法照抄既有慣例
（`test_schedule.py:315-318`）；worker 驅動照抄 `test_schedule.py:320-325`——
`web.conn.commit()` 之後 `background_module.app().run_worker(wait=False)`，走真的佇列，
不是假的。
"""

import json
import unittest
from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

import app.background as background_module
import app.main as main
import app.schedule as schedule_module
import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.identity import repository as identity_repo
from app.llm import providers
from app.meta import graph as meta_graph
from app.meta import repository as meta_repo
from app.schedule import onboarding, onboarding_slice

from .identity_test_helpers import mint_hs256

ACTOR = "測試員"
ACCOUNT_ID = "999888777"  # 外部帳號 id：純數字字串，比照既有 fixture 的形狀


def _fake_entities(campaigns: list, adsets: list = (), ads: list = ()):
    """換掉 `graph.list_entities`：依 level 回固定清單，不模擬分頁或 effective_status
    編碼——那些是 D5 自己的責任，不是這批測試要驗的東西。"""
    by_level = {"campaign": list(campaigns), "adset": list(adsets), "ad": list(ads)}

    def fake(token, account_id, level, effective_status=None):
        return by_level[level]

    return fake


def _fake_creatives(creatives_by_ad: dict):
    """換掉 `graph.list_ad_creatives`：沒有列在 `creatives_by_ad` 裡的 ad_id 回空清單
    （比照 D5 的真實行為——這個 key 依然存在，只是素材是空的）。"""
    def fake(token, ad_ids):
        return {ad_id: creatives_by_ad.get(ad_id, []) for ad_id in ad_ids}

    return fake


def _fenced_conclusions(conclusions: list) -> str:
    body = json.dumps({"conclusions": conclusions}, ensure_ascii=False)
    return f"這是一段判讀說明文字。\n\n```json\n{body}\n```"


def _one_conclusion(**overrides) -> dict:
    item = {
        "text": "外送折扣碼的廣告在週末的每次點擊成本比平日低四成",
        "scope": "brand", "confidence": "moderate",
        "evidence": "8 個週末 vs 21 個平日，同一個廣告組合",
        "sample_note": "只有 12 天有購買追蹤，其餘用點擊數判讀",
    }
    item.update(overrides)
    return item


def _fake_provider(rendered_output: str) -> providers.FakeProvider:
    return providers.FakeProvider(response=providers.ProviderResponse(
        output_text=rendered_output, structured=None,
        usage=providers.Usage(input_tokens=500, output_tokens=200), stop_reason="end_turn",
    ))


class _FailByMarkerProvider:
    """測試 4（fan-in）專用：`providers.FakeProvider` 每次呼叫回同一個固定回覆，沒辦法讓
    「兩個活動平行各跑一次分析師」裡只有其中一個失敗——兩個 job 打的是同一個 PROVIDER
    實例、同一個 `complete()`，唯一能分辨是哪個活動的線索是 prompt 內容本身（活動 id 會
    原樣出現在 D8 segment [4]-1 的 JSON 裡，`json.dumps(..., indent=2)` 固定印成
    `"id": "c2"` 這種形狀）。這是本檔自己的小道具，不是要取代 `FakeProvider`。"""

    name = "fake"

    def __init__(self, fail_marker: str, response: providers.ProviderResponse):
        self.fail_marker = fail_marker
        self.response = response
        self.calls: list = []

    def complete(self, *, model, system, messages, max_tokens, timeout_s=120.0,
                 effort=None, tools=None, org_id=None):
        self.calls.append({"messages": messages})
        if self.fail_marker in messages[0]["content"]:
            raise providers.ProviderError("模擬這個活動的分析師失敗")
        return self.response


class _OnboardingReadTestBase(unittest.TestCase):
    """共用：換掉 `graph.list_entities`／`list_ad_creatives`／`onboarding.PROVIDER`
    （tearDown 復原，比照 `test_schedule.py:315-318`／`test_meta_daily_spend.py:154,159`
    既有的「存舊值、tearDown 還原」寫法），掛好這個測試模組自己的 background task
    （`schedule_module.register_tasks()`——DSN 每個測試模組不同，見 jobs.py 檔頭），
    以及建帳號／品牌／花費列的小工具。"""

    def setUp(self):
        self._orig_list_entities = meta_graph.list_entities
        self._orig_list_ad_creatives = meta_graph.list_ad_creatives
        self._orig_provider = onboarding.PROVIDER
        schedule_module.register_tasks()
        self.client = TestClient(main.app)

    def tearDown(self):
        meta_graph.list_entities = self._orig_list_entities
        meta_graph.list_ad_creatives = self._orig_list_ad_creatives
        onboarding.PROVIDER = self._orig_provider

    def _make_org(self, suffix: str) -> tuple:
        org_id = f"org_onb_test_{suffix}_{uuid4().hex[:10]}"
        web.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (org_id, org_id),
        )
        user_id = uuid4()
        email = f"onb-test-{suffix}-{user_id.hex[:8]}@example.com"
        identity_repo.create_user(web.conn, user_id, email)
        identity_repo.create_membership(web.conn, org_id, user_id, "owner")
        web.conn.commit()
        return org_id, mint_hs256(sub=str(user_id), email=email)

    @staticmethod
    def _headers(token: str, org_id: str) -> dict:
        return {"Authorization": f"Bearer {token}", "X-Org-Id": org_id}

    def _setup_brand_with_account(self, suffix: str) -> tuple:
        """回傳 `(org_id, token, brand_id, ad_account_internal_id)`：綁好一個 Meta 帳號、
        存好一天的花費列——`_compute_frozen_facts` 沒有東西可讀就是 400
        `no_spend_data`，這批測試要驗的東西跟這個錯誤無關，所以每支都先鋪好這一天。"""
        org_id, token = self._make_org(suffix)
        meta_repo.save_token(web.conn, org_id, "meta-token")
        meta_repo.upsert_accounts(web.conn, org_id, [
            {"account_id": ACCOUNT_ID, "name": "測試廣告帳號", "currency": "TWD"},
        ])
        web.conn.commit()
        account_row = next(a for a in meta_repo.list_accounts(web.conn, org_id)
                            if a["account_id"] == ACCOUNT_ID)
        ad_account_id = account_row["id"]
        brand = bi_repo.create_brand(
            web.conn, org_id=org_id, name=f"測試品牌：{suffix}", client_name=None, actor=ACTOR,
        )
        meta_repo.bind(web.conn, org_id, brand["id"], ad_account_id)
        web.conn.commit()
        self._insert_spend_row(org_id, ad_account_id, "campaign", "c1", "活動一", "c1")
        return org_id, token, brand["id"], ad_account_id

    def _insert_spend_row(self, org_id, ad_account_id, level, entity_id, entity_name,
                           campaign_id) -> None:
        row = {
            "level": level, "entity_id": entity_id, "entity_name": entity_name,
            "campaign_id": campaign_id, "adset_id": None, "ad_id": None,
            "spend_date": date(2026, 8, 1),
            "spend": Decimal("100.00"), "impressions": 1000, "clicks": 50, "roas": None,
            "actions": None, "action_values": None,
            "attribution_window": "7d_click,1d_view",
        }
        meta_repo.upsert_entity_spend(web.conn, org_id, ad_account_id, [row])
        web.conn.commit()

    def _run_worker(self) -> None:
        web.conn.commit()
        background_module.app().run_worker(wait=False)

    @staticmethod
    def _campaign(campaign_id: str = "c1", name: str = "活動一", status: str = "ACTIVE") -> dict:
        return {"id": campaign_id, "name": name, "effective_status": status}

    @staticmethod
    def _adset(adset_id: str, campaign_id: str, name: str = "組合一") -> dict:
        return {
            "id": adset_id, "name": name, "effective_status": "ACTIVE",
            "campaign_id": campaign_id, "targeting": {"age_min": 18},
            "optimization_goal": "OFFSITE_CONVERSIONS", "billing_event": "IMPRESSIONS",
        }

    @staticmethod
    def _ad(ad_id: str, campaign_id: str, name: str = "廣告一") -> dict:
        return {"id": ad_id, "name": name, "effective_status": "ACTIVE",
                "campaign_id": campaign_id}


# -- 1. 生成不寫帳本 -------------------------------------------------------------------

class GenerationWritesNothingToLedgerTest(_OnboardingReadTestBase):
    def test_running_a_read_without_accepting_writes_zero_ledger_rows(self):
        """資料正確性（票 S2 done-check 1）：跑完一次讀取、不勾選任何結論，
        `learning_ledger` 一列都不該多出來，結論仍然讀得回來（在 llm_task 那一列裡，
        `accepted` 顯示 False）。"""
        org_id, token, brand_id, ad_account_id = self._setup_brand_with_account("gen")
        meta_graph.list_entities = _fake_entities(
            [self._campaign()], [self._adset("as1", "c1")], [self._ad("ad1", "c1")],
        )
        meta_graph.list_ad_creatives = _fake_creatives({"ad1": [{"body": "文案"}]})
        onboarding.PROVIDER = _fake_provider(_fenced_conclusions([_one_conclusion()]))
        headers = self._headers(token, org_id)

        before = web.conn.execute(
            "SELECT count(*) AS n FROM learning_ledger WHERE brand_id = %s", (brand_id,)
        ).fetchone()["n"]

        resp = self.client.post(
            f"/api/schedule/brands/{brand_id}/onboarding-read", headers=headers,
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        after = web.conn.execute(
            "SELECT count(*) AS n FROM learning_ledger WHERE brand_id = %s", (brand_id,)
        ).fetchone()["n"]
        self.assertEqual(after, before, "沒有人勾選採用，learning_ledger 不該多出任何一列")

        body = self.client.get(
            f"/api/schedule/brands/{brand_id}/onboarding-read", headers=headers,
        ).json()
        conclusions = body["read"]["jobs"][0]["conclusions"]
        self.assertEqual(len(conclusions), 1)
        self.assertEqual(conclusions[0]["text"], _one_conclusion()["text"])
        self.assertFalse(conclusions[0]["accepted"], "沒勾過，不該顯示已接受")


# -- 2. 逐條接受／全選／不預先打勾／imported 標記 ---------------------------------------

class AcceptPerConclusionTest(_OnboardingReadTestBase):
    def test_ticking_one_writes_one_row_then_select_all_writes_the_rest(self):
        """資料正確性（票 S2 done-check 2／3，兩條併成一支——D15 明講不重複驗兩遍）：
        勾 1 條 → 剛好多一列且是被勾的那條；全選 → 補齊其餘兩條，已經接受過的那條不重複
        入帳；讀取剛完成時沒有任何一條預先打勾；寫進去的列 `source_track` 標成
        imported，不是這套系統自己賺到的。"""
        org_id, token, brand_id, ad_account_id = self._setup_brand_with_account("accept")
        meta_graph.list_entities = _fake_entities(
            [self._campaign()], [self._adset("as1", "c1")], [self._ad("ad1", "c1")],
        )
        meta_graph.list_ad_creatives = _fake_creatives({"ad1": [{"body": "文案"}]})
        texts = ["結論一", "結論二", "結論三"]
        onboarding.PROVIDER = _fake_provider(
            _fenced_conclusions([_one_conclusion(text=t) for t in texts])
        )
        headers = self._headers(token, org_id)

        self.client.post(f"/api/schedule/brands/{brand_id}/onboarding-read", headers=headers)
        self._run_worker()

        body = self.client.get(
            f"/api/schedule/brands/{brand_id}/onboarding-read", headers=headers,
        ).json()
        job = body["read"]["jobs"][0]
        task_id = job["task_id"]
        self.assertEqual(
            [c["accepted"] for c in job["conclusions"]], [False, False, False],
            "讀取剛完成，任何一條都不該預先打勾",
        )

        resp = self.client.post(
            f"/api/schedule/brands/{brand_id}/onboarding-read/accept",
            json={"task_id": task_id, "indexes": [1]}, headers=headers,
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        rows = list(web.conn.execute(
            "SELECT learning_text, source_track FROM learning_ledger WHERE brand_id = %s",
            (brand_id,),
        ))
        self.assertEqual(len(rows), 1, "勾一條，只該多出一列")
        self.assertEqual(rows[0]["learning_text"], texts[1], "多出來的那一列該是被勾的那一條")
        self.assertEqual(
            rows[0]["source_track"], bi_repo.SOURCE_TRACK_IMPORTED,
            "接手既有帳號讀回來的結論，source_track 該標成 imported",
        )

        resp = self.client.post(
            f"/api/schedule/brands/{brand_id}/onboarding-read/accept",
            json={"task_id": task_id, "indexes": [0, 1, 2]}, headers=headers,
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        rows = list(web.conn.execute(
            "SELECT learning_text FROM learning_ledger WHERE brand_id = %s"
            " ORDER BY learning_text",
            (brand_id,),
        ))
        self.assertEqual(
            [r["learning_text"] for r in rows], sorted(texts),
            "全選之後三條都在，重複勾過的那條不該變成兩列",
        )


# -- 3. 兩個活動平行成功（ADR 0042 修正版點名的那支）-------------------------------------

class ParallelCampaignsBothSucceedTest(_OnboardingReadTestBase):
    def test_two_campaigns_both_reach_succeeded_neither_refused(self):
        """money（ADR 0042 修正版明講的那支測試）：鎖字面值是
        `onboarding_read:{account}:{campaign}`，不是 `onboarding_read:{brand}`——鎖抓太寬
        會讓第二個活動的 job 直接被拒收，錢等於白花一次還是查不到帳；鎖抓太窄又會讓同一份
        工作被算兩次錢。兩個活動各自成功一次、都不被拒收，證明鎖的範圍抓對了。"""
        org_id, token, brand_id, ad_account_id = self._setup_brand_with_account("parallel")
        # c2 也要有數字，否則它會被 dispatch 正確地跳過（只有 c1 派得出分析員），
        # 這支要驗的「兩個活動」就只剩一個。
        self._insert_spend_row(org_id, ad_account_id, "campaign", "c2", "活動二", "c2")
        campaigns = [self._campaign("c1", "活動一"), self._campaign("c2", "活動二")]
        meta_graph.list_entities = _fake_entities(
            campaigns,
            [self._adset("as1", "c1"), self._adset("as2", "c2")],
            [self._ad("ad1", "c1"), self._ad("ad2", "c2")],
        )
        meta_graph.list_ad_creatives = _fake_creatives(
            {"ad1": [{"body": "文案一"}], "ad2": [{"body": "文案二"}]}
        )
        onboarding.PROVIDER = _fake_provider(_fenced_conclusions([_one_conclusion()]))
        headers = self._headers(token, org_id)

        resp = self.client.post(
            f"/api/schedule/brands/{brand_id}/onboarding-read", headers=headers,
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self._run_worker()

        rows = list(web.conn.execute(
            "SELECT status FROM llm_task WHERE brand_id = %s AND task_type = 'onboarding_read'",
            (brand_id,),
        ))
        self.assertEqual(len(rows), 2, "兩個活動各自一列，不是被鎖擋掉、也不是被合併")
        self.assertEqual(
            {r["status"] for r in rows}, {"succeeded"},
            "兩個活動都該成功，不該有任何一個被鎖拒收",
        )


# -- 4. fan-in 計數：一個失敗、只重跑那一個 ----------------------------------------------

class FanInCountsTest(_OnboardingReadTestBase):
    def test_one_failed_job_then_redispatching_only_it_finishes_the_read(self):
        """資料正確性（票 S2 done-check 6）：兩個活動裡故意讓一個的分析師失敗，
        「全部完成」（succeeded == expected）該是 False；只重跑那一個活動之後變 True，
        另一個活動不會跟著多跑一次。目前沒有『只重跑一個活動』的 HTTP 端點（見報告
        problems），這裡直接呼叫 procrastinate task body 本身模擬重跑，其餘欄位照抄
        失敗那一列存的 `context_scope_json`（`read_id`／`frozen_facts`／`expected_jobs`
        是整個讀取共用的一份，不是重新算一次——跟 dispatch 當時完全一樣）。"""
        org_id, token, brand_id, ad_account_id = self._setup_brand_with_account("fanin")
        # c2 也要有數字，否則它會被 dispatch 正確地跳過（只有 c1 派得出分析員），
        # 這支要驗的「兩個活動」就只剩一個。
        self._insert_spend_row(org_id, ad_account_id, "campaign", "c2", "活動二", "c2")
        campaigns = [self._campaign("c1", "活動一"), self._campaign("c2", "活動二")]
        meta_graph.list_entities = _fake_entities(
            campaigns,
            [self._adset("as1", "c1"), self._adset("as2", "c2")],
            [self._ad("ad1", "c1"), self._ad("ad2", "c2")],
        )
        meta_graph.list_ad_creatives = _fake_creatives(
            {"ad1": [{"body": "文案一"}], "ad2": [{"body": "文案二"}]}
        )
        ok_response = providers.ProviderResponse(
            output_text=_fenced_conclusions([_one_conclusion()]), structured=None,
            usage=providers.Usage(input_tokens=500, output_tokens=200), stop_reason="end_turn",
        )
        onboarding.PROVIDER = _FailByMarkerProvider('"id": "c2"', ok_response)
        headers = self._headers(token, org_id)

        self.client.post(f"/api/schedule/brands/{brand_id}/onboarding-read", headers=headers)
        self._run_worker()

        body = self.client.get(
            f"/api/schedule/brands/{brand_id}/onboarding-read", headers=headers,
        ).json()
        read = body["read"]
        self.assertEqual(read["expected"], 2)
        self.assertFalse(read["finished"], "一個活動失敗，全部完成該是 False")

        c1_rows_before = {r["id"] for r in web.conn.execute(
            "SELECT id FROM llm_task WHERE brand_id = %s"
            "   AND context_scope_json->>'campaign_id' = 'c1'", (brand_id,),
        )}
        c2_scope = web.conn.execute(
            "SELECT context_scope_json FROM llm_task WHERE brand_id = %s"
            "   AND context_scope_json->>'campaign_id' = 'c2' ORDER BY started_at LIMIT 1",
            (brand_id,),
        ).fetchone()["context_scope_json"]

        onboarding.PROVIDER = _fake_provider(_fenced_conclusions([_one_conclusion()]))
        onboarding.onboarding_read(
            org_id=org_id, brand_id=brand_id, read_id=c2_scope["onboarding_read_id"],
            ad_account_id=c2_scope["ad_account_id"],
            account_external_id=c2_scope["account_external_id"],
            campaign_id="c2", campaign_name="活動二", campaign_effective_status="ACTIVE",
            expected_jobs=c2_scope["expected_jobs"], frozen_facts=c2_scope["frozen_facts"],
        )

        body = self.client.get(
            f"/api/schedule/brands/{brand_id}/onboarding-read", headers=headers,
        ).json()
        self.assertTrue(body["read"]["finished"], "重跑那一個活動之後，全部完成該是 True")

        c1_rows_after = {r["id"] for r in web.conn.execute(
            "SELECT id FROM llm_task WHERE brand_id = %s"
            "   AND context_scope_json->>'campaign_id' = 'c1'", (brand_id,),
        )}
        self.assertEqual(
            c1_rows_before, c1_rows_after, "重跑 c2 不該讓 c1 跟著多出新的一列",
        )


# -- 5. 回不出素材的廣告要被點名 ----------------------------------------------------------

class UnreadableAdIsReportedTest(_OnboardingReadTestBase):
    def test_ad_with_no_creative_appears_as_unreadable_not_dropped(self):
        """資料正確性（票 S2 done-check 7）：Meta 回不出素材的廣告要出現在
        `unreadable_ads` 裡，不能悄悄從清單裡消失——斷言「被靜悄悄丟掉」必須在這裡失敗。"""
        org_id, token, brand_id, ad_account_id = self._setup_brand_with_account("unreadable")
        meta_graph.list_entities = _fake_entities(
            [self._campaign()], [self._adset("as1", "c1")],
            [self._ad("ad1", "c1", "讀得到的廣告"), self._ad("ad2", "c1", "讀不到素材的廣告")],
        )
        meta_graph.list_ad_creatives = _fake_creatives({"ad1": [{"body": "文案"}]})
        onboarding.PROVIDER = _fake_provider(_fenced_conclusions([_one_conclusion()]))
        headers = self._headers(token, org_id)

        self.client.post(f"/api/schedule/brands/{brand_id}/onboarding-read", headers=headers)
        self._run_worker()

        body = self.client.get(
            f"/api/schedule/brands/{brand_id}/onboarding-read", headers=headers,
        ).json()
        unreadable = body["read"]["jobs"][0]["unreadable_ads"]
        self.assertEqual(
            unreadable, [{"ad_id": "ad2", "name": "讀不到素材的廣告"}],
            "回不出素材的廣告要被點名，不能整筆消失",
        )


class CampaignWithoutNumbersIsReportedTest(_OnboardingReadTestBase):
    def test_campaign_with_no_stored_rows_is_skipped_but_named(self):
        """資料正確性：Meta 列得出來、但這段期間手上一列數字都沒有的活動，不派分析員
        （派了只會拿到空 CSV，生出無中生有的結論），但**一定要被點名**——2026-08-31 實機
        驗收量到真帳號 58 個活動裡有 34 個屬於這類，靜靜跳過等於謊報這次讀了整個帳號。
        `_setup_brand_with_account` 只鋪了 c1 的花費列，所以 c2 就是那種活動。"""
        org_id, token, brand_id, ad_account_id = self._setup_brand_with_account("skipped")
        meta_graph.list_entities = _fake_entities(
            [self._campaign(), self._campaign("c2", "沒有數字的活動")],
            [self._adset("as1", "c1")], [self._ad("ad1", "c1")],
        )
        meta_graph.list_ad_creatives = _fake_creatives({"ad1": [{"body": "文案"}]})
        onboarding.PROVIDER = _fake_provider(_fenced_conclusions([_one_conclusion()]))
        headers = self._headers(token, org_id)

        self.client.post(f"/api/schedule/brands/{brand_id}/onboarding-read", headers=headers)
        self._run_worker()

        read = self.client.get(
            f"/api/schedule/brands/{brand_id}/onboarding-read", headers=headers,
        ).json()["read"]
        self.assertEqual(read["expected"], 1, "只有 c1 有數字，只該派一個分析員")
        self.assertEqual(
            read["campaigns_without_numbers"],
            [{"campaign_id": "c2", "name": "沒有數字的活動"}],
            "沒派人讀的活動要被點名，不能整筆消失",
        )


# -- 7. prompt 真的貼進方法論樣本數表與任務識別行 -----------------------------------------

class DailyCsvFlattensActionsWithoutInventingZeroTest(unittest.TestCase):
    def test_unreported_action_stays_blank_and_reported_value_survives(self):
        """資料正確性：`actions` 攤平成欄位是**只改形狀不改內容**（SPEC §4）——回報過的
        數字要原樣留著，沒回報的那一天要留空白、**絕不能變成 0**（`meta_entity_spend` 的
        null≠0 規矩在 CSV 這一層的樣子）。

        為什麼要有這一條：2026-08-31 實機驗收，原本每一列塞一段原始 JSON 的寫法讓一個
        722 列的活動組出 2,735,699 字元、整份提示詞 2.1 MB，撞破本機 codex CLI 的
        1,048,576 字元上限，那個活動整批讀不到。攤平之後同一份資料是 236,696 字元。
        修法只准動形狀——這支測試守的就是那個「只准動形狀」。純函式，不需要跑 worker。"""
        rows = [
            {"level": "ad", "entity_id": "ad1", "spend_date": date(2026, 8, 1),
             "actions": [{"action_type": "link_click", "value": "5"}], "action_values": None},
            {"level": "ad", "entity_id": "ad1", "spend_date": date(2026, 8, 2),
             "actions": [{"action_type": "purchase", "value": "2"}], "action_values": None},
        ]
        text = onboarding_slice.daily_csv(rows)
        header, first, second = text.strip().splitlines()

        self.assertIn("action_link_click", header)
        self.assertIn("action_purchase", header)
        self.assertNotIn("action_type", text, "攤平之後不該再出現原始 JSON 的鍵名")

        cols = header.split(",")
        link_at, purchase_at = cols.index("action_link_click"), cols.index("action_purchase")
        self.assertEqual(first.split(",")[link_at], "5", "回報過的數字要原樣留著")
        self.assertEqual(
            first.split(",")[purchase_at], "",
            "那天沒有回報 purchase 就要留空白——填 0 等於把「沒追蹤到」偽造成「真的是零」",
        )
        self.assertEqual(second.split(",")[link_at], "")
        self.assertEqual(second.split(",")[purchase_at], "2")


class PromptCarriesMethodologyTableTest(_OnboardingReadTestBase):
    def test_assembled_prompt_contains_sample_size_table_and_task_marker(self):
        """資料正確性（票 S2 done-check 8 的可執行版本，S2-DESIGN.md D15 第 6 條）：組出來
        的 prompt 真的貼進了 `ab-testing.md` 第 3 節樣本數速查表逐字內容，跟部門任務檔的
        識別行——這是模型真正需要的判斷依據有沒有到位，取代已刪掉的「grep diff 找常數」
        檢查。"""
        org_id, token, brand_id, ad_account_id = self._setup_brand_with_account("prompt")
        meta_graph.list_entities = _fake_entities(
            [self._campaign()], [self._adset("as1", "c1")], [self._ad("ad1", "c1")],
        )
        meta_graph.list_ad_creatives = _fake_creatives({"ad1": [{"body": "文案"}]})
        fake = _fake_provider(_fenced_conclusions([_one_conclusion()]))
        onboarding.PROVIDER = fake
        headers = self._headers(token, org_id)

        self.client.post(f"/api/schedule/brands/{brand_id}/onboarding-read", headers=headers)
        self._run_worker()

        self.assertEqual(len(fake.calls), 1)
        prompt_text = fake.calls[0]["messages"][0]["content"]
        self.assertIn("ONBOARDING-READ-TASK-V1", prompt_text)
        self.assertIn("## 3. 樣本數速查表", prompt_text)
        self.assertIn("1,500,000", prompt_text)
