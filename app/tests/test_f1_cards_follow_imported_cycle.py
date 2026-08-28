"""app/tests/test_f1_cards_follow_imported_cycle.py — 票 F1
（`.scratch/rehearsal-b0-fix2/issues/F1-cards-follow-imported-cycle.md`）：

匯進哪一期，卡就該出在哪一期，使用者也要能從那期看到卡。兩個獨立根因：

1. 顯示關卡：`weekly_proposals.current_cycle()` 以前只認「起始日最新」，同品牌兩期都在
   投放中時，匯入舊的那期，畫面卻只認新的那期，卡片永遠看不到（`current_cycle_older_
   cycle_surfaces_card_on_brand_endpoint`／`drop_file_import`）。
2. 建卡漏洞：批次刪除的非結案分支只重判、沒有補建卡；`reading.run()` 每次重跑都會清掉
   未處理的舊週提案卡，沒人接著呼叫 `generate()` 卡片就直接消失（`batch_delete_
   regenerates_cards`）。
3. 訊息說謊：匯入完成的訊息以前不管有沒有真的建出卡都承諾「有新的建議卡」
   （`zero_cards_message_does_not_promise_cards`）。
"""

import json
import unittest

import app.main as main
from app.ads import reading, weekly_proposals
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core.db import DEV_ORG_ID, new_id, now_iso
from app.llm.providers import FakeProvider, ProviderResponse, Usage
from app.orders import dispatch as orders_dispatch

ACTOR = "測試員"



def _fake(text):
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=300, output_tokens=150),
                            stop_reason="end_turn")


class F1CardsFollowImportedCycleTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        self.bid = bi_repo.create_brand(
            main.conn, name=f"虛構F1品牌{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)["id"]
        self._orig_provider = reading.PROVIDER
        reading.PROVIDER = FakeProvider(response=_fake(
            json.dumps({"text": "說明文字"}, ensure_ascii=False)))

    def tearDown(self):
        reading.PROVIDER = self._orig_provider

    # ---- 共用治具 ----

    def _live_cycle_with_bleeding_ad(self, start_date: str, suffix: str) -> tuple:
        """建一個 LIVE 檔期，底下兩支廣告：一支賺錢、一支虧損——這樣產品層整體還算健康
        （不會先觸發產品層停掉卡），才會落到廣告層 `bleeding_asset()`，卡片點名到廣告本身
        （票 F1 done-check 1：「returns a card naming that ad」）。回傳
        (cycle_id, campaign_name, losing_ad_name, end_date)。"""
        product_id = bi_repo.create_product(
            main.conn, self.bid, name=f"虛構F1商品{suffix}", actor=ACTOR)["id"]
        bi_repo.save_product_economics(
            main.conn, self.bid, product_id, selling_price=1000, unit_variable_cost=400,
            currency="TWD", confirmed_by=ACTOR, actor=ACTOR)
        cycle = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[product_id], pain_value=20000,
            objective="sales", actor=ACTOR, start_date=start_date, duration_days=14)
        ads_repo.update_cycle_status(main.conn, self.bid, cycle["id"], status="LIVE", actor=ACTOR)
        campaign_name = f"{suffix}測試活動"
        winning_ad = f"{suffix}賺錢廣告"
        losing_ad = f"{suffix}虧損廣告"
        ts = now_iso()
        for ad_name in (winning_ad, losing_ad):
            pkg_id, mapping_id = new_id("pkg"), new_id("xam")
            main.conn.execute(
                "INSERT INTO publishing_package (id, org_id, brand_id, campaign_cycle_id,"
                " product_id, campaign_name, adset_name, ad_name, destination_url, utm_json,"
                " status, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '{}', 'ready', %s)",
                (pkg_id, DEV_ORG_ID, self.bid, cycle["id"], product_id, campaign_name,
                 f"{suffix}測試組合", ad_name, "https://example.test", ts))
            main.conn.execute(
                "INSERT INTO external_ad_mapping (id, org_id, brand_id, publishing_package_id,"
                " campaign_cycle_id, platform, claim_status, confirmed_by, confirmed_at,"
                " created_at) VALUES (%s, %s, %s, %s, %s, 'meta', 'confirmed', %s, %s, %s)",
                (mapping_id, DEV_ORG_ID, self.bid, pkg_id, cycle["id"], ACTOR, ts, ts))
        main.conn.commit()
        return cycle["id"], campaign_name, winning_ad, losing_ad, cycle["end_date"]

    def _bleeding_csv(self, campaign_name: str, winning_ad: str, losing_ad: str,
                      *, date_start: str = "", date_end: str = "") -> str:
        date_cols = ""
        date_vals = ""
        if date_start:
            date_cols = "報告開始,報告結束,"
            date_vals = f"{date_start},{date_end},"
        header = f"{date_cols}行銷活動名稱,廣告名稱,曝光次數,連結點擊次數,花費金額,購買次數,購買轉換價值\n"
        row1 = f"{date_vals}{campaign_name},{winning_ad},20000,400,5000,10,15000\n"
        row2 = f"{date_vals}{campaign_name},{losing_ad},20000,400,5000,0,0\n"
        return header + row1 + row2

    # ---- done-check 1：品牌層週提案 API 要認匯入的那一期，不是起始日最新的那一期 ----

    def test_import_into_older_live_cycle_surfaces_card_on_brand_endpoint(self):
        older_id, older_campaign, _older_win, older_losing_ad, _end = \
            self._live_cycle_with_bleeding_ad("2026-06-01", "舊")
        newer_id, _newer_campaign, _newer_win, _newer_losing_ad, _end2 = \
            self._live_cycle_with_bleeding_ad("2026-07-01", "新")
        self.assertNotEqual(older_id, newer_id)

        csv_text = self._bleeding_csv(older_campaign, _older_win, older_losing_ad)
        resp = self.client.post(f"/api/campaigns/{self.bid}/{older_id}/performance/csv",
                                files={"perf_file": ("perf.csv", csv_text, "text/csv")})
        self.assertEqual(resp.status_code, 200, resp.text)
        # R2 審查抓到：action_url 以前指到 WarroomPage（S8 檔期建置畫面），那裡沒有
        # 任何週提案卡 UI——真正顯示卡片的是品牌層駕駛艙，網址不帶檔期。
        self.assertEqual(resp.json()["weekly_cards"]["action_url"], f"/app/brands/{self.bid}")

        # 前端唯一真的會呼叫的品牌層端點（票裡明白點名，六個顯示呼叫端之一）。
        proposals_resp = self.client.get(f"/api/campaigns/brands/{self.bid}/weekly/proposals")
        self.assertEqual(proposals_resp.status_code, 200)
        data = proposals_resp.json()["data"]
        self.assertEqual(data["cycle_id"], older_id)  # 認的是匯入進去的那期，不是起始日更新的那期
        targets = [p["target"] for p in data["proposals"]]
        self.assertIn(older_losing_ad, targets)  # 卡片點名到那支虧損的廣告

    # ---- done-check 2：拖檔口一樣要補到位（LIVE 首判 bootstrap 原本整段沒有） ----

    def test_drop_file_import_into_older_live_cycle_surfaces_card(self):
        older_id, older_campaign, older_win, older_losing_ad, older_end = \
            self._live_cycle_with_bleeding_ad("2026-06-01", "拖舊")
        newer_id, _c, _w, _l, _e = self._live_cycle_with_bleeding_ad("2026-08-01", "拖新")
        self.assertNotEqual(older_id, newer_id)

        csv_text = self._bleeding_csv(older_campaign, older_win, older_losing_ad,
                                      date_start="2026-06-01", date_end=older_end)
        result = orders_dispatch.import_dropped_file(
            main.conn, self.bid, filename="meta.csv", content=csv_text.encode("utf-8"),
            actor=ACTOR, today="2026-06-10")
        self.assertEqual(result.kind, "meta_ads_csv")
        self.assertEqual(result.errors, [])

        proposals_resp = self.client.get(f"/api/campaigns/brands/{self.bid}/weekly/proposals")
        data = proposals_resp.json()["data"]
        self.assertEqual(data["cycle_id"], older_id)
        targets = [p["target"] for p in data["proposals"]]
        self.assertIn(older_losing_ad, targets)

    # ---- done-check 3：批次刪除非結案分支要補建卡，不能被 reading.run() 清掉就沒了 ----

    def test_batch_delete_on_non_closed_cycle_regenerates_cards(self):
        cycle_id, campaign_name, winning_ad, losing_ad, _end = \
            self._live_cycle_with_bleeding_ad("2026-07-01", "刪")

        first_csv = self._bleeding_csv(campaign_name, winning_ad, losing_ad)
        resp = self.client.post(f"/api/campaigns/{self.bid}/{cycle_id}/performance/csv",
                                files={"perf_file": ("perf.csv", first_csv, "text/csv")})
        self.assertEqual(resp.status_code, 200, resp.text)
        cards_before = weekly_proposals.list_cards(main.conn, self.bid, cycle_id)
        self.assertTrue(any(c["status"] == "GENERATED" for c in cards_before))

        # 第二批：同樣的虧損訊號，數字不同避免被去重吃掉——刪掉其中一批之後另一批還在，
        # 檔期依舊是非結案、依舊有虧損訊號，不是「刪光資料」這種退化情境。
        second_csv = ("行銷活動名稱,廣告名稱,曝光次數,連結點擊次數,花費金額,購買次數,購買轉換價值\n"
                     f"{campaign_name},{winning_ad},21000,410,5100,10,15200\n"
                     f"{campaign_name},{losing_ad},21000,410,5100,0,0\n")
        resp2 = self.client.post(f"/api/campaigns/{self.bid}/{cycle_id}/performance/csv",
                                 files={"perf_file": ("perf.csv", second_csv, "text/csv")})
        self.assertEqual(resp2.status_code, 200, resp2.text)

        batches = self.client.get(
            f"/api/campaigns/{self.bid}/{cycle_id}/performance/batches").json()["data"]["items"]
        self.assertEqual(len(batches), 2)
        oldest_batch_id = batches[-1]["batch_id"]

        cycle = ads_repo.get_cycle(main.conn, self.bid, cycle_id)
        self.assertNotEqual(cycle["status"], "CLOSED")  # 走的是非結案分支

        del_resp = self.client.delete(
            f"/api/campaigns/{self.bid}/{cycle_id}/performance/batches/{oldest_batch_id}")
        self.assertEqual(del_resp.status_code, 200, del_resp.text)

        cards_after = weekly_proposals.list_cards(main.conn, self.bid, cycle_id)
        pending_after = [c for c in cards_after if c["status"] == "GENERATED"]
        self.assertTrue(pending_after, "刪批後 reading.run() 清掉舊卡，非結案分支要補建新卡")
        self.assertIn(losing_ad, [c["target"] for c in pending_after])

    # ---- done-check 4：沒有卡就不能承諾有卡 ----

    def test_zero_cards_message_does_not_promise_cards(self):
        cycle = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[], pain_value=10000, objective="sales",
            actor=ACTOR, start_date="2026-07-01", duration_days=14)
        ads_repo.update_cycle_status(main.conn, self.bid, cycle["id"], status="LIVE", actor=ACTOR)
        main.conn.commit()

        # 沒有掛任何產品，成效落到品牌層／檔期層，判讀不出任何停掉／加碼／疲勞訊號，
        # generate() 因此一張卡都不會建。
        csv_text = "行銷活動名稱,花費金額\n沒有訊號的活動,3000\n"
        resp = self.client.post(f"/api/campaigns/{self.bid}/{cycle['id']}/performance/csv",
                                files={"perf_file": ("perf.csv", csv_text, "text/csv")})
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()

        cards = weekly_proposals.list_cards(main.conn, self.bid, cycle["id"])
        self.assertEqual(cards, [])  # 真的沒有卡
        self.assertNotIn("建議卡", body["rerun_message"])  # 訊息不能承諾不存在的卡
        self.assertEqual(body["weekly_cards"]["generated"], 0)

    # ---- done-check 1 R2：兩期都候著卡時，tie-break 不能退回「起始日最新」 ----
    # 審查意見指出：舊 fix 在「有 GENERATED 卡的那期」裡還是照 list_cycles() 的
    # start_date DESC 挑第一個——同品牌兩期都候著卡時，等於又退回「起始日最新」，
    # 複製了票要修的症狀。改法：候選期之間比「候著的卡最後建出的時間」，新匯入的
    # 那期卡片剛建出、時間戳最新，才會贏過先前就候著、沒人動過的那期。

    def test_older_import_hidden_when_newer_cycle_already_has_a_pending_card(self):
        newer_id, newer_campaign, newer_win, newer_losing_ad, _e = \
            self._live_cycle_with_bleeding_ad("2026-07-01", "先新")
        # 先讓「新」那期候著一張沒人理的舊卡。
        csv_stale = self._bleeding_csv(newer_campaign, newer_win, newer_losing_ad)
        resp_stale = self.client.post(
            f"/api/campaigns/{self.bid}/{newer_id}/performance/csv",
            files={"perf_file": ("perf.csv", csv_stale, "text/csv")})
        self.assertEqual(resp_stale.status_code, 200, resp_stale.text)
        stale_cards = weekly_proposals.list_cards(main.conn, self.bid, newer_id)
        self.assertTrue(any(c["status"] == "GENERATED" for c in stale_cards))

        older_id, older_campaign, older_win, older_losing_ad, _e2 = \
            self._live_cycle_with_bleeding_ad("2026-06-01", "後舊")
        self.assertNotEqual(older_id, newer_id)

        # 再匯入舊期——這是票的原始症狀：使用者剛匯進去的資料要能看見。
        csv_fresh = self._bleeding_csv(older_campaign, older_win, older_losing_ad)
        resp = self.client.post(f"/api/campaigns/{self.bid}/{older_id}/performance/csv",
                                files={"perf_file": ("perf.csv", csv_fresh, "text/csv")})
        self.assertEqual(resp.status_code, 200, resp.text)

        proposals_resp = self.client.get(f"/api/campaigns/brands/{self.bid}/weekly/proposals")
        data = proposals_resp.json()["data"]
        self.assertEqual(data["cycle_id"], older_id)  # 剛匯入的那期，不是先候著卡的那期
        targets = [p["target"] for p in data["proposals"]]
        self.assertIn(older_losing_ad, targets)

    # ---- done-check 2 R2：approve 不能靠 current_cycle() 這個會變動的推斷重找卡 ----
    # 審查意見指出：GET 顯示卡片時解析出的檔期，跟按核可當下 approve 端點自己重新
    # 呼叫 current_cycle() 解析出的檔期，中間如果有別的匯入插進來，兩次解析可能對不
    # 上——使用者對著畫面上明明看得到的卡按核可卻收到 400。改法：approve／skip
    # 直接用 recommendation_id 查出它真正所在的檔期，不透過 current_cycle() 猜。

    def test_approve_targets_different_cycle_than_the_get_that_displayed_it(self):
        older_id, older_campaign, older_win, older_losing_ad, _e = \
            self._live_cycle_with_bleeding_ad("2026-06-01", "核舊")
        csv_older = self._bleeding_csv(older_campaign, older_win, older_losing_ad)
        resp = self.client.post(f"/api/campaigns/{self.bid}/{older_id}/performance/csv",
                                files={"perf_file": ("perf.csv", csv_older, "text/csv")})
        self.assertEqual(resp.status_code, 200, resp.text)

        proposals_resp = self.client.get(f"/api/campaigns/brands/{self.bid}/weekly/proposals")
        data = proposals_resp.json()["data"]
        self.assertEqual(data["cycle_id"], older_id)
        card = next(p for p in data["proposals"] if p["target"] == older_losing_ad)
        recommendation_id = card["id"]

        # GET 之後、使用者按核可之前，另一期插進來搶了 current_cycle() 的解析結果。
        newer_id, newer_campaign, newer_win, newer_losing_ad, _e2 = \
            self._live_cycle_with_bleeding_ad("2026-08-01", "核新")
        csv_newer = self._bleeding_csv(newer_campaign, newer_win, newer_losing_ad)
        resp2 = self.client.post(f"/api/campaigns/{self.bid}/{newer_id}/performance/csv",
                                 files={"perf_file": ("perf.csv", csv_newer, "text/csv")})
        self.assertEqual(resp2.status_code, 200, resp2.text)

        approve_resp = self.client.post(
            f"/api/campaigns/brands/{self.bid}/weekly/proposals/{recommendation_id}/approve",
            json={})
        self.assertEqual(approve_resp.status_code, 200, approve_resp.text)


if __name__ == "__main__":
    unittest.main()
