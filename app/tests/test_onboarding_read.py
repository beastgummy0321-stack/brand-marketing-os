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
from app.schedule import onboarding, onboarding_slice, onboarding_slice_csv, onboarding_slice_totals

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
    原樣出現在 D8 segment [4]-1 的 `structure_text()` 開頭那行 `campaign：[c2] ...`
    ——A4，票 S2b：`structure_text()` 從整包 JSON 改成事實卡文字之後，這個標記字串
    跟著換了形狀，但「只匹配 c2 的 prompt、不匹配 c1 的」這個唯一性沒變）。這是本檔自己
    的小道具，不是要取代 `FakeProvider`。"""

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
        onboarding.PROVIDER = _FailByMarkerProvider("campaign：[c2]", ok_response)
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

class BucketedCsvFlattensActionsWithoutInventingZeroTest(unittest.TestCase):
    def test_unreported_action_stays_blank_and_reported_value_survives(self):
        """資料正確性：`actions` 攤平成欄位是**只改形狀不改內容**（SPEC §4）——回報過的
        數字要原樣留著，沒回報的那個桶要留空白、**絕不能變成 0**（`meta_entity_spend` 的
        null≠0 規矩在 CSV 這一層的樣子）。

        為什麼要有這一條：2026-08-31 實機驗收，原本每一列塞一段原始 JSON 的寫法讓一個
        722 列的活動組出 2,735,699 字元、整份提示詞 2.1 MB，撞破本機 codex CLI 的
        1,048,576 字元上限，那個活動整批讀不到。攤平之後同一份資料是 236,696 字元。
        修法只准動形狀——這支測試守的就是那個「只准動形狀」。純函式，不需要跑 worker。

        **B1（票 S2b／ADR 0045）：粒度從「一天」變成「一個時間桶」，這條規矩一個字沒鬆**
        （ADR 0045：「Null ≠ zero survives the change of grain」）——所以兩列資料改成分別
        落在平日桶跟週末桶（2026-08-03 是週一、2026-08-01 是週六），才驗得到「這個桶
        沒回報過這個種類」跟「這個桶回報的值是 0」的差別。"""
        rows = [
            {"level": "ad", "entity_id": "ad1", "spend_date": date(2026, 8, 3),
             "actions": [{"action_type": "link_click", "value": "5"}], "action_values": None},
            {"level": "ad", "entity_id": "ad1", "spend_date": date(2026, 8, 1),
             "actions": [{"action_type": "purchase", "value": "2"}], "action_values": None},
        ]
        _entity_dict, text, kept, omitted = onboarding_slice_csv.bucketed_csv(
            rows, date(2026, 8, 1), date(2026, 8, 31)
        )
        self.assertEqual(omitted, [], "兩種都有活動，A1 不該省掉任何一欄")
        self.assertEqual(sorted(kept), ["action_link_click", "action_purchase"])
        header, first, second = text.strip().splitlines()

        self.assertIn("action_link_click", header)
        self.assertIn("action_purchase", header)
        self.assertNotIn("action_type", text, "攤平之後不該再出現原始 JSON 的鍵名")

        cols = header.split(",")
        link_at, purchase_at = cols.index("action_link_click"), cols.index("action_purchase")
        self.assertEqual(first.split(",")[link_at], "5", "回報過的數字要原樣留著")
        self.assertEqual(
            first.split(",")[purchase_at], "",
            "那個桶沒有回報 purchase 就要留空白——填 0 等於把「沒追蹤到」偽造成「真的是零」",
        )
        self.assertEqual(second.split(",")[link_at], "")
        self.assertEqual(second.split(",")[purchase_at], "2")
        self.assertNotEqual(
            first.split(",")[cols.index("bucket")], second.split(",")[cols.index("bucket")],
            "平日跟週末永遠是兩個不同的桶，不准併——ADR 0045 唯一不准改的那一刀",
        )


class BucketedCsvOmitsAllZeroColumnsTest(unittest.TestCase):
    def test_zero_sum_column_dropped_and_named_in_totals_note(self):
        """資料正確性（A1，票 S2b）：一個欄位只有在**整個活動的窗口加總起來是 0** 才不送——
        `video_view` 兩天都回報過、但兩天都是 0，加總是 0，所以整欄不進表頭；`link_click`
        兩天加總是 8，照常送。省掉的欄位不能悄悄消失：`totals_text()` 那一行要點名，
        「省了什麼」跟「送了什麼」兩份名單都是 `daily_csv()` 算的，`totals_text()` 只是把
        它們印出來，不重算一次（票 S2b：「do not compute it twice」）。

        （A3，票 S2b：這支測試同時是「A1 的測試」，多驗一件事——`entity_name` 這種長名字
        不該在資料列裡重複出現，應該只在多回傳的實體對照表裡出現一次；`entity_id` 這個
        短 id 才是資料列自己要留的東西。B1 之後判斷「加總是不是 0」的範圍仍然是**整個
        窗口**，不是單一個桶——欄位表頭是整張表共用的，一個桶有活動就得留這一欄。）"""
        long_name = "測試用很長的廣告名稱・不該在每一列 CSV 資料裡重複出現一次"
        rows = [
            {"level": "ad", "entity_id": "ad1", "entity_name": long_name,
             "spend_date": date(2026, 8, 1),
             "actions": [
                 {"action_type": "link_click", "value": "5"},
                 {"action_type": "video_view", "value": "0"},
             ], "action_values": None},
            {"level": "ad", "entity_id": "ad1", "entity_name": long_name,
             "spend_date": date(2026, 8, 2),
             "actions": [
                 {"action_type": "link_click", "value": "3"},
                 {"action_type": "video_view", "value": "0"},
             ], "action_values": None},
        ]
        entity_dict, csv_text, kept, omitted = onboarding_slice_csv.bucketed_csv(
            rows, date(2026, 8, 1), date(2026, 8, 31)
        )
        header = csv_text.strip().splitlines()[0]

        self.assertIn("action_link_click", header, "整個窗口加總不是 0，欄位要在")
        self.assertNotIn(
            "action_video_view", csv_text,
            "整個窗口加總是 0，這一欄不該送——CSV 裡不該再看得到它的名字",
        )
        self.assertEqual(kept, ["action_link_click"])
        self.assertEqual(omitted, ["action_video_view"])

        self.assertNotIn(
            long_name, csv_text,
            "A3：長名字不該在資料列裡重複出現——名字只在對照表講一次",
        )
        self.assertNotIn(
            "entity_name", header,
            "A3：entity_name 欄位本身也不該再進表頭",
        )
        self.assertIn("ad1", csv_text, "短 id 還是要留在資料列裡，不然沒辦法對回對照表")
        self.assertIn(long_name, entity_dict, "A3：對照表要把名字講出來，不能兩邊都不見")
        self.assertIn("ad1", entity_dict, "A3：對照表要用 id 對應回名字")
        self.assertIn("ad", entity_dict, "A3：對照表也要講層級，不只是名字")

        note = onboarding_slice_totals.totals_text({}, [], kept, omitted)
        self.assertIn(
            "action_video_view", note,
            "省掉的欄位要在期間總計那一行點名——presence and absence are both facts",
        )
        self.assertIn(
            "1 種有活動照常送出", note,
            "有送的種類數（presence）也要講，不能只講省了什麼",
        )


class BucketSumsEqualTheDailyValuesTheyReplaceTest(unittest.TestCase):
    def test_bucket_totals_match_the_raw_daily_sums(self):
        """資料正確性（B1 閘門 1，票 S2b／ADR 0045：「Bucketing may change shape; it may
        not change a total.」）：一個桶的 spend／impressions／clicks 必須等於它取代的那幾天
        原始值加起來。花費是**先加總再四捨五入**，不是把每天四捨五入過的值相加——這支
        fixture 三天各 0.005 元，逐日四捨五入是 0.01×3＝0.03，正確答案是 0.015→0.02。

        先證過紅：把 `_bucket_row()` 的 spend 改成 `sum(_round_money(r["spend"]) …)`
        （先捨入再加總），這支從綠翻紅：`AssertionError: '0.03' != '0.02'`；改回
        `_round_money(_sum_or_none(...))` 才又綠。"""
        rows = [
            {"level": "ad", "entity_id": "ad1", "spend_date": date(2026, 8, 3),
             "spend": Decimal("0.005"), "impressions": 100, "clicks": 7, "roas": None,
             "actions": None, "action_values": None},
            {"level": "ad", "entity_id": "ad1", "spend_date": date(2026, 8, 4),
             "spend": Decimal("0.005"), "impressions": 250, "clicks": 3, "roas": None,
             "actions": None, "action_values": None},
            {"level": "ad", "entity_id": "ad1", "spend_date": date(2026, 8, 5),
             "spend": Decimal("0.005"), "impressions": 1, "clicks": 0, "roas": None,
             "actions": None, "action_values": None},
        ]
        _dict, csv_text, _kept, _omitted = onboarding_slice_csv.bucketed_csv(
            rows, date(2026, 8, 1), date(2026, 8, 31)
        )
        lines = csv_text.strip().splitlines()
        cols = lines[0].split(",")
        bucket_rows = [
            line.split(",") for line in lines[1:]
            if line.split(",")[cols.index("spend_date")] == ""
        ]
        self.assertEqual(len(bucket_rows), 1, "三天都是平日，同一個月——就是同一個桶")
        cells = bucket_rows[0]

        self.assertEqual(cells[cols.index("impressions")], "351", "曝光加總不准變")
        self.assertEqual(cells[cols.index("clicks")], "10", "點擊加總不准變")
        self.assertEqual(
            cells[cols.index("spend")], "0.02",
            "花費要先加總（0.015）再四捨五入成 0.02——先捨入再相加會變成 0.03",
        )
        self.assertEqual(cells[cols.index("days_with_data")], "3")
        self.assertEqual(
            cells[cols.index("days_covered")], "21",
            "2026-08 這個月有 21 個平日，這是這個桶涵蓋的天數，不是有資料的天數",
        )


class EmptyBucketIsNamedNotSilentlyDroppedTest(unittest.TestCase):
    def test_bucket_with_no_data_is_named_in_coverage_and_roas_is_never_zero(self):
        """資料正確性（B1 閘門 2，票 S2b／ADR 0045）：換了粒度之後，「缺席」跟「零」還是
        兩件不同的事。ADR 0045 原句要求空桶留一列，2026-08-31 拿真帳號量過改成「由涵蓋
        範圍那節逐個點名」（195 個實體 × 24 桶有 83% 是空的，照原句做列數反而漲 61%，
        改動寫在 ADR 0045 自己那一節）——**點名不是沉默，這支測試守的就是那個點名**。
        同時守 ROAS：這個桶有資料但一天都沒有 ROAS，那一格要空白，不能填 0（ADR 0045：
        「its ROAS is `None`, not `0`」）。

        先證過紅：把 `coverage_text()` 的 `empty_text` 那段拿掉，這支從綠翻紅：
        `AssertionError: '2026-08/週末' not found in ...`；把 `_bucket_roas()` 的
        `return None` 改成 `return Decimal(0)`，第二段斷言從綠翻紅：
        `AssertionError: '0' != ''`。"""
        rows = [
            {"level": "ad", "entity_id": "ad1", "spend_date": date(2026, 8, 3),
             "spend": Decimal("10"), "impressions": 100, "clicks": 7, "roas": None,
             "actions": None, "action_values": None},
        ]
        _dict, csv_text, _kept, _omitted = onboarding_slice_csv.bucketed_csv(
            rows, date(2026, 8, 1), date(2026, 8, 31)
        )
        lines = csv_text.strip().splitlines()
        cols = lines[0].split(",")
        bucket_rows = [
            line.split(",") for line in lines[1:]
            if line.split(",")[cols.index("spend_date")] == ""
        ]
        self.assertEqual(
            len(bucket_rows), 1,
            "23 個空桶不進表（它們在涵蓋範圍那節點名），只有 8/3 那個平日桶有資料",
        )
        self.assertEqual(
            bucket_rows[0][cols.index("roas")], "",
            "這個桶一天都沒有 ROAS，那一格要空白——填 0 等於斷言「投了沒有回報」",
        )
        self.assertEqual(bucket_rows[0][cols.index("days_with_roas")], "0")

        coverage = onboarding_slice_totals.coverage_text(
            rows, date(2026, 8, 1), date(2026, 8, 31),
            [{"level": "ad", "entity_id": "ad1", "entity_name": "廣告一"}],
        )
        self.assertIn(
            "2026-08/週末", coverage,
            "整個窗口沒資料的桶要被逐個點名——不進表格可以，消失不行",
        )
        self.assertIn("1／2", coverage, "點名要帶分母：24 個桶裡有幾個是空的")


class OutlierDaysSurviveBucketingTest(unittest.TestCase):
    def test_highest_spend_and_highest_conversion_days_go_through_verbatim(self):
        """資料正確性（B1，票 S2b）：分桶最容易磨掉「某一天爆單」這類單日發現，所以每個桶
        額外原封送出花費最高的那天與轉換最高的那天（最多兩列，去重）。**這條規則沒有任何
        門檻常數**——用排名不用倍數，那個倍數沒有來源，沒有來源的數字不准進程式
        （憲章；`app/methodology/ab-testing.md:73`）。

        「轉換」用品牌自己的 `conversion_goal` 對應的 action_type（跟 CPA 分母同一份，
        `meta_repo.conversion_action_types()`），不是「所有 actions 加起來最多」——這支
        fixture 就是那個差別：8/3 有 800 次 link_click、0 筆成交，8/5 有 9 筆成交、花費
        最低。先證過紅：把 `_outlier_days()` 的轉換分數改成「所有 actions 加總」，這支從
        綠翻紅（挑到 8/3，`AssertionError: '2026-08-05' not found in ...`）。"""
        rows = [
            {"level": "ad", "entity_id": "ad1", "spend_date": date(2026, 8, 3),
             "spend": Decimal("500"), "impressions": 9000, "clicks": 800, "roas": None,
             "actions": [{"action_type": "link_click", "value": "800"}], "action_values": None},
            {"level": "ad", "entity_id": "ad1", "spend_date": date(2026, 8, 4),
             "spend": Decimal("100"), "impressions": 500, "clicks": 20, "roas": None,
             "actions": [{"action_type": "link_click", "value": "20"}], "action_values": None},
            {"level": "ad", "entity_id": "ad1", "spend_date": date(2026, 8, 5),
             "spend": Decimal("50"), "impressions": 300, "clicks": 10, "roas": Decimal("11"),
             "actions": [
                 {"action_type": "link_click", "value": "10"},
                 {"action_type": "purchase", "value": "9"},
             ], "action_values": None},
        ]
        _dict, csv_text, _kept, _omitted = onboarding_slice_csv.bucketed_csv(
            rows, date(2026, 8, 1), date(2026, 8, 31),
            meta_repo.conversion_action_types("purchase"),
        )
        lines = csv_text.strip().splitlines()
        cols = lines[0].split(",")
        day_rows = [
            line.split(",")[cols.index("spend_date")] for line in lines[1:]
            if line.split(",")[cols.index("spend_date")] != ""
        ]
        self.assertIn("2026-08-03", day_rows, "花費最高的那天要原封送出")
        self.assertIn(
            "2026-08-05", day_rows,
            "轉換最高的那天要原封送出——這一天花費最低，只看花費會漏掉它",
        )
        self.assertNotIn("2026-08-04", day_rows, "兩名以外的日子留在桶裡，不額外送")
        self.assertEqual(len(day_rows), 2, "每個桶最多兩列，沒有門檻常數可以調")


class CoverageTextComputesLongestGapTest(unittest.TestCase):
    def test_known_gap_pattern_yields_exact_gap_boundaries(self):
        """資料正確性（A2，票 S2b）：涵蓋範圍是外殼算好的，不是問模型算的——這支測試守
        的是算出來的最長缺口起訖日要跟餵進去的資料完全對得上，包括票 S2b 明講的三個邊界：
        一列資料都沒有的實體（`adB`，roster 有名字但 rows 裡完全找不到）、缺口只落在窗口
        最前面（`adD`，只缺第一天）、窗口裡天天都有資料所以沒有缺口（`adC`）。

        `roster` 跟 `rows` 是兩份不同的東西：`adB` 只在 `roster`（呼叫端從 adsets／ads
        原封組出來的完整名單）裡，`rows`（Meta 真的回報過的那幾天）裡一列都沒有——這支
        測試同時證明「一列資料都沒有的實體不會從涵蓋範圍那段消失」（票 S2b 明講的規矩）。"""
        since, until = date(2026, 8, 1), date(2026, 8, 10)

        def _row(entity_id, day, spend=Decimal("1"), roas=None):
            return {
                "level": "ad", "entity_id": entity_id, "spend_date": date(2026, 8, day),
                "spend": spend, "roas": roas,
            }

        rows = [
            # adA：缺口在中間（8/4～8/7，4 天），一天有花費卻沒 ROAS（8/1）。
            _row("adA", 1, spend=Decimal("10"), roas=None),
            _row("adA", 2, spend=Decimal("5"), roas=Decimal("2.0")),
            _row("adA", 3, spend=Decimal("0"), roas=None),
            _row("adA", 8, spend=Decimal("1"), roas=Decimal("3.0")),
            _row("adA", 9, spend=Decimal("1"), roas=Decimal("3.0")),
            _row("adA", 10, spend=Decimal("0"), roas=None),
            # adB：完全沒有列在 rows 裡——只出現在 roster。
            # adC：窗口裡天天都有資料，沒有缺口。
            *[_row("adC", d, roas=Decimal("1.0")) for d in range(1, 11)],
            # adD：只缺第一天——缺口落在窗口最前面。
            *[_row("adD", d, roas=Decimal("1.0")) for d in range(2, 11)],
        ]
        roster = [
            {"level": "ad", "entity_id": "adA", "entity_name": "A"},
            {"level": "ad", "entity_id": "adB", "entity_name": "B"},
            {"level": "ad", "entity_id": "adC", "entity_name": "C"},
            {"level": "ad", "entity_id": "adD", "entity_name": "D"},
        ]

        text = onboarding_slice_totals.coverage_text(rows, since, until, roster)
        lines = {line.split("（")[0]: line for line in text.splitlines() if line.startswith("- ")}

        self.assertIn("## 每個實體的涵蓋範圍（外殼算好的）", text)
        self.assertIn("窗口 10 天", lines["- [ad] A"], "10 天窗口的天數要算對")
        self.assertIn("最長缺口 2026-08-04～2026-08-07", lines["- [ad] A"], "中間缺口的起訖要準")
        self.assertIn(
            "有花費卻沒 ROAS 1 天", lines["- [ad] A"], "8/3、8/10 花費是 0，不算「有花費」",
        )
        self.assertIn("首末有資料 2026-08-01～2026-08-10", lines["- [ad] A"])

        self.assertIn(
            "最長缺口 2026-08-01～2026-08-10", lines["- [ad] B"],
            "roster 裡有、rows 裡完全沒有的實體，缺口是整段窗口，不能從清單裡消失",
        )
        self.assertIn("有資料 0 天", lines["- [ad] B"])
        self.assertIn("首末有資料 無", lines["- [ad] B"])

        self.assertIn("最長缺口 無缺口", lines["- [ad] C"], "天天都有資料就不該報出一個缺口")

        self.assertIn(
            "最長缺口 2026-08-01～2026-08-01", lines["- [ad] D"],
            "缺口只落在窗口最前面那一天，也要算對，不能只找『第一筆到最後一筆資料之間』",
        )


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


# -- 8. A4 保險絲：抽不出 body／title 就送原始 JSON ---------------------------------------

class CreativeFuseSendsRawJsonOnUnexpectedShapeTest(unittest.TestCase):
    def test_ad_copy_in_unexpected_field_triggers_fuse_and_raw_json_passes_through(self):
        """資料正確性（A4，票 S2b）：`structure_text()` 把素材攤成事實卡（body／title／
        call_to_action_type／media_ids），但文案如果不在 `_creative_variants()` 認得的
        三種形狀裡任何一個欄位——這裡故意把文案藏進一個沒人預期到的鍵名
        `unexpected_copy_field`——保險絲要點火：這則素材的原始 JSON 原封不動送進文字，
        不能編出空的 body／title 假裝有讀到，更不能把這則廣告當成「Meta 回不出素材」
        整筆消失（那是另一條路，`unreadable`，這裡的素材明明存在，只是形狀認不得）。
        純函式，不需要跑 worker。"""
        campaign = {"id": "c1", "name": "活動一", "effective_status": "ACTIVE"}
        weird_creative = {
            "id": "cr1",
            "unexpected_copy_field": "廣告文案藏在這個沒人預期到的鍵名裡",
        }
        ads = [{"id": "ad1", "name": "怪素材廣告", "effective_status": "ACTIVE"}]
        creatives_by_ad = {"ad1": [weird_creative]}

        text, unreadable = onboarding_slice.structure_text(campaign, [], ads, creatives_by_ad)

        self.assertEqual(
            unreadable, [],
            "這則廣告的素材不是空的，只是形狀認不得——不算進『Meta 回不出素材』那份名單",
        )
        self.assertIn("保險絲觸發", text, "抽不出 body 也抽不出 title 就該點火保險絲")
        self.assertIn(
            json.dumps(weird_creative, ensure_ascii=False), text,
            "保險絲點火後，這則素材的原始 JSON 要原封不動出現在文字裡",
        )
        self.assertNotIn(
            "  body：廣告文案藏在這個沒人預期到的鍵名裡", text,
            "不能把藏起來的文案獨立抽出來當成一行 body 印出來——那是臆測，不是保險絲",
        )
        self.assertIn(
            "保險絲觸發（抽不出 body 也抽不出 title）", text,
            "這則素材真的一句文案都沒有，理由就該是這一句——這條路上它是真話",
        )

    def test_fuse_reason_names_the_branch_that_fired_not_a_hardcoded_sentence(self):
        """資料正確性（票 S2b 完整性審查，2026-08-31）：保險絲有四條各自不同的路，
        `_ad_fact_card()` 原本不論走哪一條都印死同一句「抽不出 body 也抽不出 title」。
        真帳號 368741390835357 實測 34 次觸發裡 27 次那句是假的——緊接著印出去的原始
        JSON 裡明明就有 body，系統對分析員說了一句被自己下一行當場推翻的話。這裡用的是
        「兩套編碼都帶文案」那條路（object_story_spec 跟 asset_feed_spec 都有文案，外殼
        拒絕挑哪一半算數）。

        先證過紅：把 `_ad_fact_card()` 的 f-string 改回寫死那句「這則素材抽不出 body
        也抽不出 title」，這支從綠翻紅：`AssertionError: '保險絲觸發（object_story_spec
        與 asset_feed_spec 兩邊都帶文案，讀不出哪一份算數）' not found in ...`，改回來
        才又綠。"""
        campaign = {"id": "c1", "name": "活動一", "effective_status": "ACTIVE"}
        both_encodings = {
            "id": "cr_both",
            "object_story_spec": {"link_data": {"message": "舊版文案", "name": "舊版標題"}},
            "asset_feed_spec": {"bodies": [{"text": "動態素材文案"}]},
        }
        ads = [{"id": "ad1", "name": "兩套編碼廣告", "effective_status": "ACTIVE"}]

        text, _unreadable = onboarding_slice.structure_text(
            campaign, [], ads, {"ad1": [both_encodings]}
        )

        self.assertIn(
            f"保險絲觸發（{onboarding_slice._FUSE_BOTH_ENCODINGS}）", text,
            "理由要講出真正觸發的那一條路，不是四條路共用一句話",
        )
        self.assertNotIn(
            "抽不出 body 也抽不出 title", text,
            "這則素材抽得出 body（下一行的原始 JSON 裡就有兩份），說抽不出來就是說謊",
        )
        self.assertIn(
            "動態素材文案", text, "保險絲點火後原始 JSON 要原封送出，兩套文案都在裡面",
        )


# -- 9. A4 審查回應：三支獨立審查者都抓到、機器閘門原本守不住的資料正確性缺陷 --------------

class VideoCreativeTitleFieldIsNotDroppedTest(unittest.TestCase):
    def test_video_data_title_key_differs_from_link_data_and_is_read_correctly(self):
        """資料正確性（A4 審查回應）：`video_data` 的標題鍵是 `title`，`link_data` 的標題
        鍵是 `name`——不是同一組鍵名。原本 `_creative_variants()` 三種形狀共用
        `data.get("name")`，讀 `video_data` 時找不到 `name`，印出 `title：None`，Meta
        真的給的標題整個消失且保險絲不會點火（因為 `message` 找到了）。ADR 0045：
        「No rewriting of ad copy. Creative text reaches the model verbatim, always.」"""
        creative = {
            "object_story_spec": {
                "video_data": {
                    "message": "夏天到了，補水面膜五折",
                    "title": "限時五折｜補水面膜",
                    "call_to_action": {"type": "SHOP_NOW"},
                    "video_id": "v123",
                },
            },
        }
        variants, _fuse = onboarding_slice._creative_variants(creative)
        self.assertEqual(len(variants), 1)
        self.assertEqual(
            variants[0]["title"], "限時五折｜補水面膜",
            "video_data 的標題該讀 title 這個鍵，不是 link_data 用的 name",
        )
        self.assertEqual(variants[0]["body"], "夏天到了，補水面膜五折")


class ZeroSumSplitDoesNotProveZeroFromMissingValueTest(unittest.TestCase):
    def test_action_type_with_no_reported_value_is_kept_not_omitted(self):
        """資料正確性（A1 審查回應）：一個種類 Meta 回報過、但沒給 `value`（不是 0，是
        沒有），不能拿去證明「這個活動整個窗口加總是 0」——原本 `_zero_sum_split()` 先
        `totals.setdefault(action_type, Decimal(0))` 再判斷 `raw is None`，把「無法
        證明」偷渡成「證明是 0」，這正是 `action_cells()` 那條 null≠0 規矩要擋住、卻在
        加總這一步破例的地方，`totals_text()` 因此會印出一句從沒被證明過的
        「這裡整個窗口加總是 0」。"""
        rows = [
            {"actions": [
                {"action_type": "lead", "value": None},
                {"action_type": "link_click", "value": "2"},
            ]},
            {"actions": [{"action_type": "lead"}]},
        ]
        action_kept, _value_kept, action_omitted, _value_omitted = (
            onboarding_slice_csv.action_columns(rows)
        )
        self.assertIn(
            "lead", action_kept,
            "從沒給過數字，不等於證明是 0，不該被當成整欄加總是 0 而省略",
        )
        self.assertNotIn("lead", action_omitted)


class AdsetFactCardCarriesBudgetModeFieldsTest(unittest.TestCase):
    def test_effective_status_and_budget_mode_fields_are_not_dropped(self):
        """資料正確性（A4 審查回應）：`optimization_goal`／`billing_event` 就是
        ADR 0045 點名的「the budget mode (a structural fact)」本身——`app/meta/graph.py`
        的 `_ENTITY_FIELDS["adset"]` 本來就打這兩個欄位加 `effective_status` 回來，
        `_adset_fact_card()` 原本漏接，PAUSED 的廣告組跟正在跑的廣告組長得一模一樣，
        部門任務檔「平台自己分配的預算，不是公平的實驗」那條線就沒有欄位可以依據。"""
        adset = {
            "id": "as1", "name": "AS one", "effective_status": "PAUSED",
            "optimization_goal": "OFFSITE_CONVERSIONS", "billing_event": "IMPRESSIONS",
            "targeting": {},
        }
        card = onboarding_slice._adset_fact_card(adset)
        self.assertIn("PAUSED", card, "effective_status 不該從卡片裡消失")
        self.assertIn("OFFSITE_CONVERSIONS", card, "optimization_goal 是結構性事實，不該消失")
        self.assertIn("IMPRESSIONS", card, "billing_event 是結構性事實，不該消失")


# -- 10. A4 完整性審查（2026-08-31，真帳號 368741390835357）：綠燈閘門守不住的兩個資料
#         正確性缺陷，兩支都是拿真帳號量到的形狀原封不動剪下來當 fixture ---------------

class LabelledAssetResolvesAdAssetLabelObjectTest(unittest.TestCase):
    def test_asset_customization_rules_label_is_an_object_not_a_string(self):
        """資料正確性（bug 1）：真帳號 368741390835357 驗證過（2026-08-31 完整性審查），
        `asset_customization_rules` 的 `body_label`／`title_label` 跟資產自己的
        `adlabels`，兩邊都是 AdAssetLabel 物件（`{"name": ..., "id": ...}`），不是純
        字串——這裡 fixture 就是那個真實形狀剪下來的最小版本。原本
        `_resolve_labelled_asset()` 直接拿這個物件去跟 `adlabel.get("name")`（字串）
        比對，字典永遠不等於字串，比對永遠失敗：這個帳號 23 則用
        asset_customization_rules 的素材全部因此掉進保險絲，量到 147,946 字元的原始
        JSON 取代了本該只要 14,829 字元的事實卡。先證過紅：把
        `_resolve_labelled_asset()` 改回只比 `adlabel.get("name") == label`（label
        還是物件），這支從綠翻紅，`AssertionError: 0 != 1`（variants 變成空清單），
        改回來才又綠。"""
        creative = {
            "id": "cr1",
            "asset_feed_spec": {
                "bodies": [
                    {"adlabels": [{"name": "body_label_1", "id": "1001"}],
                     "text": "真的素材文案"},
                ],
                "titles": [
                    {"adlabels": [{"name": "title_label_1", "id": "2001"}],
                     "text": "真的素材標題"},
                ],
                "call_to_action_types": ["SHOP_NOW"],
                "asset_customization_rules": [
                    {
                        "customization_spec": {"age_min": 18, "age_max": 65},
                        "body_label": {"name": "body_label_1", "id": "1001"},
                        "title_label": {"name": "title_label_1", "id": "2001"},
                        "priority": 1,
                    },
                ],
            },
        }
        variants, _fuse = onboarding_slice._creative_variants(creative)
        self.assertEqual(len(variants), 1, "label 物件解析成功，不該落進保險絲的空清單")
        self.assertEqual(variants[0]["body"], "真的素材文案")
        self.assertEqual(variants[0]["title"], "真的素材標題")


class AssetFeedSpecCtaAndDescriptionsAreNotDroppedTest(unittest.TestCase):
    def test_call_to_action_types_read_as_plain_strings_and_descriptions_survive(self):
        """資料正確性（bug 2／2b）：真帳號驗證過（2026-08-31 完整性審查）
        `asset_feed_spec` 回的鍵是 `call_to_action_types`（純字串陣列），從來不是
        原本讀的 `call_to_actions`——那個鍵這個帳號 158 則素材一次都沒出現過，CTA
        因此永遠是 `None`。`descriptions` 這欄逐字文案原本完全沒讀，真帳號 77 則素材
        （23 則走 rules、54 則沒有）因此悄悄漏掉一段文案，保險絲還不會點火（因為
        body 找到了）——票明講一句摘要都不算，何況整欄不見。先證過紅：把
        `call_to_action_types` 改回 `call_to_actions`、拿掉讀 `descriptions` 那幾行，
        這支從綠翻紅，`AssertionError: None != 'SHOP_NOW'`，改回來才又綠。"""
        creative = {
            "id": "cr2",
            "asset_feed_spec": {
                "bodies": [{"text": "沒有規則配對的主文案"}],
                "call_to_action_types": ["SHOP_NOW"],
                "descriptions": [{"text": "逐字照登的補充說明"}],
            },
        }
        variants, _fuse = onboarding_slice._creative_variants(creative)
        self.assertTrue(variants, "body 讀得到就不該落進保險絲")
        self.assertEqual(
            variants[0]["call_to_action_type"], "SHOP_NOW",
            "call_to_action_types 是純字串陣列，只有一項就該直接印出來，不是 None",
        )
        descriptions_seen = [
            v["extra"]["descriptions"]
            for v in variants if v.get("extra", {}).get("descriptions")
        ]
        self.assertTrue(descriptions_seen, "descriptions 欄位原本完全沒讀，逐字文案不該消失")
        self.assertEqual(descriptions_seen[0], ["逐字照登的補充說明"])


class AssetFeedSpecUnpairedBodiesAndTitlesAreHonestTest(unittest.TestCase):
    def test_no_rules_shape_lists_bodies_and_titles_separately_not_as_fake_variants(self):
        """資料正確性（完整性審查修正 1，2026-08-31）：`asset_feed_spec` 有
        `bodies`／`titles` 但沒有 `asset_customization_rules`（真帳號 158 則素材裡
        92 則是這個形狀，最常見的一種）——Meta 投遞時才配對哪句 body 配哪句 title，
        我們讀不出配對。上一輪把每個 body／title 各自印成一則「變體」，帶著
        `title：（無）`／`media_ids：[]`／`placement_count：1`，看起來像一則廣告缺了
        標題、缺了媒材、只有一條版位規則——三件事全是編出來的結構，Meta 根本沒給。

        先證過紅：把 `_creative_variants()` 沒有 rules 那個分支改回舊邏輯（body／title
        各自造一個 `placement_count: 1` 的變體），這支從綠翻紅：
        `AssertionError: 2 != 4`（4 個假變體 vs 現在正確的 1 筆 unpaired 紀錄），改回來
        才又綠。"""
        creative = {
            "id": "cr3",
            "asset_feed_spec": {
                "bodies": [{"text": "文案一，逐字照登"}, {"text": "文案二，逐字照登"}],
                "titles": [{"text": "標題一"}, {"text": "標題二"}],
                "call_to_action_types": ["SHOP_NOW"],
            },
        }
        variants, _fuse = onboarding_slice._creative_variants(creative)
        self.assertEqual(
            len(variants), 1,
            "沒有規則就沒辦法配對——該回一筆 unpaired 紀錄，不是 body/title 各自的假變體",
        )
        self.assertTrue(variants[0].get("unpaired"))
        self.assertEqual(variants[0]["bodies"], ["文案一，逐字照登", "文案二，逐字照登"])
        self.assertEqual(variants[0]["titles"], ["標題一", "標題二"])

        card = onboarding_slice._ad_fact_card(
            {"id": "ad3", "name": "廣告三", "effective_status": "ACTIVE"}, [creative],
        )
        self.assertIn("文案一，逐字照登", card)
        self.assertIn("文案二，逐字照登", card)
        self.assertIn("標題一", card)
        self.assertIn("標題二", card)
        self.assertIn("投遞時才配對", card)
        self.assertNotIn("placement_count", card)
        self.assertNotIn("title：（無）", card)
        self.assertNotIn("media_ids：[]", card)


class RoundSigFigsDoesNotEmitScientificNotationTest(unittest.TestCase):
    def test_large_roas_stays_plain_digits_not_e_notation(self):
        """資料正確性（完整性審查修正 2，2026-08-31）：`_round_sig_figs()` 自己的
        docstring 講「留在 Decimal 就不會像 float 那樣印成科學記號」，上一輪只修了
        小數字那半（`_round_money` 磨到分不會、`_round_sig_figs` 磨小數字也不會），
        磨一個 ≥ 1000 的大數字（一個誇張的 ROAS 或 CPM）留下的 `Decimal.quantize()`
        結果內部指數是正的，`str()`／CSV 儲存格印出來一樣是 `1.23E+3`，跟 docstring
        講的正好相反。先證過紅：拿掉 `format(rounded, "f")` 那行重建，直接回傳
        `value.quantize(quantum, ...)`，這支從綠翻紅：
        `AssertionError: '1.23E+3' != '1230'`，改回來才又綠。"""
        result = onboarding_slice_csv._round_sig_figs(Decimal("1234.5"), 3)
        self.assertEqual(str(result), "1230", "大數字四捨五入到有效數字不該印成科學記號")
        self.assertNotIn("E", str(result))
        # 小數字那半（上一輪已修好的）不能被這次的改動弄壞。
        small = onboarding_slice_csv._round_sig_figs(Decimal("0.0001234"), 3)
        self.assertEqual(str(small), "0.000123")


# -- 11. A4 完整性審查第二輪（2026-08-31，真帳號 368741390835357）：三個獨立審查者
#         （realdata／fuse／gate）逐一量到、綠燈閘門守不住的資料正確性缺陷 -------------

class TemplateDataShapeAndChildOnlyAttachmentsAreNotDroppedTest(unittest.TestCase):
    def test_template_data_shape_is_recognised(self):
        """資料正確性（A4 完整性審查第二輪）：`object_story_spec.template_data` 是
        `_STORY_SHAPES` 原本不認得的第四種真實形狀（真帳號 158 則素材裡 25 則是這個
        形狀，剪自真帳號 120247917807670671／975229208598019），落到 `asset_feed_spec`
        分支或保險絲，輪播卡片文案整個消失。先證過紅：把新加的
        `("template_data", ...)` 那筆 `_STORY_SHAPES` 拿掉，這支從綠翻紅：
        `AssertionError: 0 != 3`（`_STORY_SHAPES` 沒有形狀能比對，fixture 又沒有
        `asset_feed_spec` 可以退回去，`_creative_variants()` 落到最後回空清單），
        加回來才又綠。"""
        creative = {
            "id": "cr_template",
            "object_story_spec": {
                "template_data": {
                    "message": "美式也可以放口袋",
                    "name": "{{product.name}}",
                    "call_to_action": {"type": "SHOP_NOW"},
                    "child_attachments": [
                        {"name": "撕開一顆就夠", "description": "咖啡因x牛磺酸xB12"},
                        {"name": "體驗極致效率", "description": "咖啡x提神飲料x軟糖"},
                    ],
                },
            },
        }
        variants, _fuse = onboarding_slice._creative_variants(creative)
        self.assertEqual(len(variants), 3, "父層一則＋兩張輪播卡片＝3 則變體")
        self.assertEqual(variants[0]["body"], "美式也可以放口袋")
        card_bodies = [v["body"] for v in variants]
        self.assertIn("咖啡因x牛磺酸xB12", card_bodies)
        self.assertIn("咖啡x提神飲料x軟糖", card_bodies)

    def test_child_attachments_are_read_even_when_parent_has_no_body_or_title(self):
        """資料正確性（同一輪審查）：剪自真帳號 120246213077800671／2202339803873237，
        `link_data` 沒有 `message` 也沒有 `name`，文案全部在 `child_attachments` 裡——
        原本 `if not (body or title): continue` 沒看 `child_attachments` 就跳過整個
        形狀，輪播卡片文案 100% 消失，這則素材又沒有 `asset_feed_spec`，最後落進空清單
        保險絲——保險絲確實點了火，但送出去的原始 JSON 裡讀不到任何逐張卡片抽出來的
        `body`，不是「送整包原始資料」該有的樣子（票明講：讀不出來才送原始 JSON，這裡
        明明讀得出來）。先證過紅：把 continue 判斷式改回不看 `child_attachments`，
        這支從綠翻紅：`AssertionError: 0 != 2`（variants 變空清單），改回來才又綠。"""
        creative = {
            "id": "cr_child_only",
            "object_story_spec": {
                "link_data": {
                    "link": "https://beastprime.com.tw/",
                    "image_hash": "abc",
                    "call_to_action": {"type": "SHOP_NOW"},
                    "child_attachments": [
                        {
                            "name": "下午的狀態，一顆就夠",
                            "description": "150mg 咖啡因機能軟糖",
                        },
                        {
                            "name": "一顆 $20⬇，比一杯咖啡便宜一半",
                            "description": "咖啡因 150mg｜隨身攜帶",
                        },
                    ],
                },
            },
        }
        variants, _fuse = onboarding_slice._creative_variants(creative)
        child_bodies = [
            v["body"] for v in variants
            if (v.get("ad_format") or "").endswith("child_attachment")
        ]
        self.assertEqual(len(child_bodies), 2, "兩張輪播卡片文案都要讀到，不是整個形狀被跳過")
        self.assertIn("150mg 咖啡因機能軟糖", child_bodies)
        self.assertIn("咖啡因 150mg｜隨身攜帶", child_bodies)


class CallToActionFallsBackToTopLevelFieldTest(unittest.TestCase):
    def test_missing_story_and_feed_cta_falls_back_to_creative_top_level(self):
        """資料正確性（A4 完整性審查第二輪）：真帳號 86/158 則廣告的 CTA 只在素材最
        外層的 `call_to_action_type` 有，`object_story_spec` 跟 `asset_feed_spec`
        兩邊都沒有（剪自真帳號 120250979856360671）——原本兩個分支都直接印
        None／（無），等於斷言 Meta 沒給 CTA。先證過紅：把 `_STORY_SHAPES` 分支跟
        `asset_feed_spec` 分支的 `or creative.get("call_to_action_type")` 都改回
        沒有退回層，這支從綠翻紅：`AssertionError: None != 'SHOP_NOW'`（兩個
        assertEqual 都會炸），改回來才又綠。"""
        story_creative = {
            "id": "cr_story_cta",
            "object_story_spec": {"link_data": {"message": "文案", "name": "標題"}},
            "call_to_action_type": "SHOP_NOW",
        }
        variants, _fuse = onboarding_slice._creative_variants(story_creative)
        self.assertEqual(variants[0]["call_to_action_type"], "SHOP_NOW")

        feed_creative = {
            "id": "cr_feed_cta",
            "asset_feed_spec": {"bodies": [{"text": "純 feed 文案"}]},
            "call_to_action_type": "SHOP_NOW",
        }
        variants2, _fuse2 = onboarding_slice._creative_variants(feed_creative)
        self.assertEqual(variants2[0]["call_to_action_type"], "SHOP_NOW")


class AssetCustomizationRulesUnreferencedAssetTriggersFuseTest(unittest.TestCase):
    def test_body_or_title_asset_unused_by_any_rule_returns_empty_for_fuse(self):
        """資料正確性（A4 完整性審查第二輪，真帳號 368741390835357 逐欄位驗證過）：
        這個帳號每一份 body／title 資產的 `adlabels` 常常帶著這則素材全部規則的
        label（不是各自一條），`_resolve_labelled_asset()` first-match-wins 因此把
        全部規則解析成同一組，其他 body／title 悄悄消失（帳號全域 13/39 bodies、
        12/38 titles，剪自真帳號 120241360945350671／1700019804295984）。這裡不試著
        把 label 解析得更聰明，改成分組完之後斷言涵蓋率：3 份 body 只有 2 份被規則
        用到，代表這裡的 label 解析法讀不懂這則素材的真配對，整組回空清單讓保險絲
        接手，不是只送對得到的那兩份。先證過紅：把這段涵蓋率檢查拿掉，這支從綠翻紅：
        `AssertionError: Lists differ: [{'body': ...` 不等於 `[]`（回傳 2 個不完整的
        變體，不是空清單），改回來才又綠。"""
        creative = {
            "id": "cr_rules",
            "asset_feed_spec": {
                "bodies": [
                    {"adlabels": [{"name": "b1", "id": "1"}], "text": "文案一"},
                    {"adlabels": [{"name": "b2", "id": "2"}], "text": "文案二"},
                    {"text": "文案三，沒有任何規則對得到"},
                ],
                "titles": [
                    {"adlabels": [{"name": "t1", "id": "10"}], "text": "標題一"},
                    {"adlabels": [{"name": "t2", "id": "20"}], "text": "標題二"},
                ],
                "call_to_action_types": ["SHOP_NOW"],
                "asset_customization_rules": [
                    {
                        "body_label": {"name": "b1", "id": "1"},
                        "title_label": {"name": "t1", "id": "10"},
                    },
                    {
                        "body_label": {"name": "b2", "id": "2"},
                        "title_label": {"name": "t2", "id": "20"},
                    },
                ],
            },
        }
        variants, _fuse = onboarding_slice._creative_variants(creative)
        self.assertEqual(
            variants, [],
            "文案三沒被任何規則引用到，代表這裡的 label 解析法讀不懂真配對，"
            "該整組回空清單讓保險絲送原始 JSON",
        )


class UnpairedVariantSeedsFromTopLevelTitleWhenFeedHasNoneTest(unittest.TestCase):
    def test_top_level_title_is_not_dropped_when_feed_bodies_exist_without_titles(self):
        """資料正確性（A4 完整性審查第二輪，剪自真帳號 120250288876640671）：
        `asset_feed_spec` 有 7 個 bodies 沒有 titles，素材最外層 `title` 是那句真的
        標題（'留言【試用】索取隨身包'）——原本 `_unpaired_variant_lines()` 印
        `titles（0）：`，斷言這則廣告沒有標題，其實只是沒放進 feed 那份清單。先證過
        紅：把新加的「`title_texts` 空的時候拿 `creative.get('title')` 補」那兩行
        拿掉，這支從綠翻紅：`AssertionError: Lists differ: [] != ['留言【試用】索取
        隨身包']`（titles 變回空清單），改回來才又綠。"""
        creative = {
            "id": "cr_unpaired_title",
            "title": "留言【試用】索取隨身包",
            "asset_feed_spec": {
                "bodies": [{"text": "文案一"}, {"text": "文案二"}],
                "call_to_action_types": ["SHOP_NOW"],
            },
        }
        variants, _fuse = onboarding_slice._creative_variants(creative)
        self.assertEqual(len(variants), 1)
        self.assertTrue(variants[0].get("unpaired"))
        self.assertEqual(variants[0]["titles"], ["留言【試用】索取隨身包"])

        card = onboarding_slice._ad_fact_card(
            {"id": "ad_x", "name": "廣告 X", "effective_status": "ACTIVE"}, [creative],
        )
        self.assertIn("留言【試用】索取隨身包", card)
        self.assertNotIn("titles（0）", card)


class ExtraListFieldsPrintVerbatimNotAsPythonReprTest(unittest.TestCase):
    def test_multi_line_description_is_not_escaped_into_repr(self):
        """資料正確性（A4 完整性審查第二輪，剪自真帳號一則素材的 `descriptions[0].text`
        真的帶換行）：原本 `f"  {field}：{value}"` 把清單值直接塞進 f-string，`value`
        是清單時印出來的是 Python 的 `repr()`——方括號、引號、看得見的 `\\n`，帶換行的
        真實文案因此不是逐字（票明講：a summarised quote is not a quote，跳脫符號也是
        一種改寫）。先證過紅：把 `_extra_lines()` 改回 `f"  {field}：{value}"` 那種
        單行版本，這支從綠翻紅：`AssertionError: '口袋能量 · 只留清醒！\\n喚醒你的
        內在野獸！' not found in "...descriptions：['口袋能量 · 只留清醒！\\\\n喚醒你的
        內在野獸！']"`——真的帶換行的那句話不再逐字出現，因為 repr() 把它跳脫、包了
        方括號跟引號，改回來才又通過。"""
        creative = {
            "id": "cr_desc",
            "asset_feed_spec": {
                "bodies": [{"text": "主文案"}],
                "descriptions": [{"text": "口袋能量 · 只留清醒！\n喚醒你的內在野獸！"}],
            },
        }
        card = onboarding_slice._ad_fact_card(
            {"id": "ad_desc", "name": "廣告 Desc", "effective_status": "ACTIVE"}, [creative],
        )
        self.assertIn(
            "口袋能量 · 只留清醒！\n喚醒你的內在野獸！", card,
            "多行文案要逐字出現，換行不能被跳脫成看得見的 \\n",
        )
        self.assertNotIn("['口袋能量", card, "不該印成 Python repr() 的清單字面值")


class AdsetFactCardCarriesAgeRangeAdvantageAudienceAndAllDetailedTargetingKindsTest(
    unittest.TestCase,
):
    def test_age_range_and_advantage_audience_and_other_flexible_spec_kinds_survive(self):
        """資料正確性（A4 完整性審查第二輪，真帳號 368741390835357 逐欄位驗證過）：
        (1) 30/50 個廣告組開了 `targeting_automation.advantage_audience: 1`，Meta
        因此把 `age_min`／`age_max` 灌成平台上限，廣告主真正選的年齡範圍留在
        `age_range`（剪自真帳號 120234286640980671：age_min=18／age_max=65／
        age_range=[18, 40]）；原本卡片只印前者，兩個 `age_range` 不同的廣告組會印出
        一樣的年齡帶。(2) `flexible_spec` 裡的 `behaviors`／`industries`／
        `work_positions`（27/50 個廣告組帶了其中之一，剪自真帳號 120238010821580671）
        原本完全沒被收集，卡片上唯一的 honesty counter（interests「還有 N 個未列出」）
        因此在明明還有別的鎖定沒印出來時，看起來像已經列完了。(3)
        `excluded_product_audience_specs`（剪自真帳號 120238698630100671）原本沒算進
        `exclusion_count`，真的有排除受眾的廣告組會印出 0。"""
        adset = {
            "id": "as1", "name": "AS one", "effective_status": "ACTIVE",
            "targeting": {
                "age_min": 18, "age_max": 65, "age_range": [18, 40],
                "targeting_automation": {"advantage_audience": 1},
                "flexible_spec": [{
                    "interests": [{"id": "i1", "name": "興趣一"}],
                    "behaviors": [{"id": "b1", "name": "行為一"}],
                    "industries": [{"id": "d1", "name": "產業一"}],
                    "work_positions": [{"id": "w1", "name": "職稱一"}],
                }],
                "excluded_product_audience_specs": [{"product_set_id": "1"}],
            },
        }
        card = onboarding_slice._adset_fact_card(adset)
        self.assertIn("age_range=[18, 40]", card, "廣告主真正選的年齡範圍不該被拿掉")
        self.assertIn("advantage_audience=1", card, "受眾擴張是 age_min/max 失真的原因")
        self.assertIn("behaviors（前 10／共 1 個）：行為一", card)
        self.assertIn("industries（前 10／共 1 個）：產業一", card)
        self.assertIn("work_positions（前 10／共 1 個）：職稱一", card)
        self.assertIn("exclusion_count：1", card, "excluded_product_audience_specs 也是排除")


class TotalsTextRendersMissingMetricAsBlankNotNoneLiteralTest(unittest.TestCase):
    def test_null_roas_and_cpa_render_as_blank_marker(self):
        """資料正確性（A4 完整性審查第二輪，gate 審查點名：真帳號 24 個活動 194 行
        指標全部印出裸的 Python `None`）：`totals_text()` 沒有套 `_ad_fact_card()`
        那族已經在用的 `_blank_or()`，一個活動沒有轉換事件、ROAS／CPA 是 None 時，
        f-string 直接內插印出 'None' 這個字面值——跟這整份切片一路守的 null≠0 是同一
        條線，只是漏了這一處。先證過紅：把新加的三個 `_blank_or(...)` 拿掉還原成直接
        內插 `_round_sig_figs(...)`／`_round_money(...)`，這支從綠翻紅：
        `AssertionError: 'None' unexpectedly found in`，改回來才又通過。"""
        totals = {"campaign": [{
            "entity_id": "c1", "entity_name": "活動一",
            "spend": Decimal("100.00"), "impressions": 1000, "clicks": 10,
            "ctr": None, "cpc": None, "cpm": None, "roas": None, "cpa": None,
        }]}
        text = onboarding_slice_totals.totals_text(totals, [])
        self.assertNotIn("None", text, "缺指標要印（無），不能印 Python 的 None 字面值")
        self.assertIn("ROAS （無）", text)
