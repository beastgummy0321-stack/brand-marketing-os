# -*- coding: utf-8 -*-
"""可重複執行的自我檢查（不留長駐伺服器；用 FastAPI TestClient 直接對 app 發請求）。

用暫存 DB（BRAND_OS_DB／BRAND_OS_BACKUP_DIR 指到 tempdir，不動預設 DB 路徑），
啟動時自動種好示範資料（app/seed_demo.py）。

驗證重點（依任務指定）：
1. 主要路由回 200。
2. 切到品牌 B 後，畫面上不會出現品牌 A 的名稱（品牌隔離）。
3. 新增品牌／確認事實的 POST 流程有效（PRG：303 轉址、資料真的寫入、成功訊息帶名稱）。
4. 額外把關：跨品牌存取回「找不到」、畫面上沒有內部欄位名／狀態英文值外洩、表單驗證錯誤與回填。
5. 重啟 app（重建連線＋TestClient）後資料仍在 —— 證明真的落地在 DB 檔案，不是活在記憶體。
6. 建檔精靈（DESIGN.md §19）：12 頁路由全部 200、R5 鐵律（畫面上找不到任何批次接受字樣）、
   無操作人時精靈 POST 也被導去設定操作人、W10「確認」「先存成待確認」兩個出口真的寫入
   app.brand_intelligence.repository（品牌檔案頁看得到）、花費列三種門檻狀態、W12 超限攔截
   在呼叫前攔下且三個出口都可用。

執行：python -m app.smoke_test
"""

import io
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

# 先備好暫存 DB／備份目錄的環境變數，才能 import app.main —— 它在 import 當下就會
# 連線＋跑 migrations＋備份檢查（見 app/main.py 的啟動流程）。用 mkdtemp（不是
# TemporaryDirectory）自己管生命週期：程式結束前明確關掉連線再刪目錄，避免
# Windows 上「檔案還開著就被砍」的清理期例外。
_tmpdir = tempfile.mkdtemp(prefix="brand_os_smoke_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "smoke.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "smoke_backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "smoke_uploads")

import json  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main_module  # noqa: E402
from app import seed_demo  # noqa: E402
from app.brand_intelligence import repository as repo  # noqa: E402
from app.intake import ai as intake_ai  # noqa: E402
from app.intake import script as intake_script  # noqa: E402
from app.intake import state as intake_state  # noqa: E402
from app.llm.providers import (  # noqa: E402
    MISSING_KEY_MESSAGE, FakeProvider, ProviderError, ProviderResponse, Usage,
)

# 精靈的 LLM 呼叫一律用 FakeProvider（不發真實網路請求）；網址抓取也換成假的。
# token 數刻意挑成與 §19.6 花費時間軸相同的金額（opus 費率）：
#   初掃 400k/88k -> 4.20、每題 100k/40k -> 1.50、格式修復 200k/40k -> 2.00
intake_ai.fetch_url = lambda url: (False, "")


def _fake_ai(text, in_tok, out_tok):
    intake_ai.PROVIDER = FakeProvider(response=ProviderResponse(
        output_text=text, structured=None,
        usage=Usage(input_tokens=in_tok, output_tokens=out_tok), stop_reason="end_turn"))


def _fake_ai_fail():
    intake_ai.PROVIDER = FakeProvider(exception=ProviderError(MISSING_KEY_MESSAGE))


def run():
    try:
        return _run_checks()
    finally:
        main_module.conn.close()
        shutil.rmtree(_tmpdir, ignore_errors=True)


def _run_checks():
    seed_demo.seed(main_module.conn, force=False)

    client = TestClient(main_module.app)
    failures = []

    def check(label, cond):
        status = "OK" if cond else "FAIL"
        print(f"[{status}] {label}")
        if not cond:
            failures.append(label)

    def check_intake_wizard():
        """建檔精靈（DESIGN.md §19）：12 頁路由、R5 鐵律、無操作人導流、W10 真的寫入、
        花費三種門檻狀態、W12 在呼叫前攔截且三個出口可用。用獨立、乾淨的 client 走，
        不動用前面已經設定操作人 cookie 的 client（要單獨驗證「無操作人」那條）。"""
        anon = TestClient(main_module.app)
        resp = anon.post("/brands/intake/new", data={"name": "無操作人精靈測試", "description": "x" * 20},
                          follow_redirects=False)
        check("無操作人時 POST /brands/intake/new -> 303", resp.status_code == 303)
        check("無操作人時轉址到 /settings/operator",
              resp.headers.get("location", "").startswith("/settings/operator"))

        wclient = TestClient(main_module.app)
        wclient.post("/settings/operator", data={"name": "精靈測試員", "next": "/"}, follow_redirects=False)

        # W1：GET 空表單 200 + POST 建立品牌（真的寫入 repository）並開始初掃
        resp = wclient.get("/brands/intake/new")
        check("W1 GET /brands/intake/new -> 200", resp.status_code == 200)
        photo = ("photos", ("tea.jpg", io.BytesIO(b"x" * 1000), "image/jpeg"))
        resp = wclient.post("/brands/intake/new", data={
            "name": "精靈測試茶（示範資料）", "client_name": "",
            "description": "做台灣中南部小農的烏龍與紅茶，主打單一產區、冷泡也不苦。",
            "url_1": "", "url_2": "", "url_3": "", "url_4": "", "url_5": "",
        }, files=[photo], follow_redirects=False)
        check("W1 POST -> 303（走 repository 真建立品牌）", resp.status_code == 303)
        brand_id = resp.headers["location"].split("/brands/")[1].split("/")[0]
        check("W1 真的寫入 repository.list_brands", any(b["id"] == brand_id for b in repo.list_brands(main_module.conn)))

        # 照片路由：剛上傳的 tea.jpg 開得起來，content-type 對；不存在的檔名 404。
        resp = wclient.get(f"/brands/{brand_id}/intake/photos/tea.jpg")
        check("照片路由 200（tea.jpg 真的落地）", resp.status_code == 200)
        check("照片路由 content-type 正確（image/jpeg）",
              resp.headers.get("content-type", "").startswith("image/jpeg"))
        resp = wclient.get(f"/brands/{brand_id}/intake/photos/does-not-exist.jpg")
        check("照片路由對不存在的檔名回 404", resp.status_code == 404)

        # W1 UX 陷阱回歸測試：驗證失敗（漏填描述）時，已上傳的照片要真的留住；
        # 補上描述後不帶檔案重送也要能成功——「已經留著了，不用重新選」這句話得是真的。
        photo_retry = ("photos", ("retry.png", io.BytesIO(b"y" * 2000), "image/png"))
        resp = wclient.post("/brands/intake/new", data={
            "name": "重送測試品牌（示範資料）", "client_name": "",
            "description": "",  # 故意留空觸發驗證失敗
            "url_1": "", "url_2": "", "url_3": "", "url_4": "", "url_5": "",
        }, files=[photo_retry])
        check("W1 缺描述 -> 400", resp.status_code == 400)
        check("W1 缺描述時畫面仍顯示已上傳的照片", "已經留著了，不用重新選" in resp.text and "retry.png" in resp.text)
        token_match = re.search(r'name="photo_token" value="([^"]*)"', resp.text)
        check("W1 400 回應帶著 photo_token 供重送沿用", bool(token_match and token_match.group(1)))
        retry_token = token_match.group(1) if token_match else ""
        resp = wclient.post("/brands/intake/new", data={
            "name": "重送測試品牌（示範資料）", "client_name": "",
            "description": "這次補上描述，測試照片是否沿用、不用重新選。",
            "url_1": "", "url_2": "", "url_3": "", "url_4": "", "url_5": "",
            "photo_token": retry_token,
        }, follow_redirects=False)  # 這次不帶任何檔案
        check("W1 補描述後不帶檔案重送仍成功（沿用已留照片）", resp.status_code == 303)
        retry_brand_id = resp.headers["location"].split("/brands/")[1].split("/")[0]
        retry_draft = intake_state.get_draft(retry_brand_id)
        check("重送成功後草稿確實帶著先前上傳的照片", any(p["name"] == "retry.png" for p in retry_draft["photos"]))

        # 跨草稿：retry_brand 的草稿沒有 tea.jpg（那是另一個品牌的照片）-> 404
        resp = wclient.get(f"/brands/{retry_brand_id}/intake/photos/tea.jpg")
        check("照片路由跨草稿存取回 404（retry 品牌沒有 tea.jpg）", resp.status_code == 404)
        resp = wclient.get(f"/brands/{retry_brand_id}/intake/photos/retry.png")
        check("照片路由 200（retry.png，另一個副檔名）", resp.status_code == 200)
        check("照片路由 content-type 正確（image/png）",
              resp.headers.get("content-type", "").startswith("image/png"))

        # AI 失敗（例如沒設金鑰）的人話錯誤路徑：用 retry 品牌的草稿（初掃還沒跑）驗證
        _fake_ai_fail()
        resp = wclient.get(f"/brands/{retry_brand_id}/intake/scan/progress?run=1", follow_redirects=False)
        check("AI 失敗時進度頁 ?run=1 -> 303（不當機）", resp.status_code == 303
              and "ai_failed=1" in resp.headers.get("location", ""))
        resp = wclient.get(resp.headers["location"])
        check("AI 失敗時結果頁 200，顯示人話錯誤（缺金鑰訊息）",
              resp.status_code == 200 and "尚未設定 AI 金鑰" in resp.text)
        check("AI 失敗時提供「前往設定頁」引導", "前往設定頁" in resp.text and "/settings" in resp.text)
        check("AI 失敗那筆呼叫記成失敗、不計入已花費（$ 0.00 起步）",
              intake_state.get_draft(retry_brand_id)["cost_spent"] == 0.0)

        # W2：進度頁（初掃）—— 第一次 GET 顯示進度頁，meta refresh 導向 ?run=1 真正執行
        resp = wclient.get(f"/brands/{brand_id}/intake/scan/progress")
        check("W2 GET .../scan/progress -> 200", resp.status_code == 200)
        check("W2 進度頁用 meta refresh 自我更新（無輪詢 JS）", 'http-equiv="refresh"' in resp.text)
        check("W2 找不到 spinner／動畫字樣", "animation" not in resp.text and "spinner" not in resp.text.lower())
        _fake_ai(json.dumps({"impressions": intake_script.SCAN_IMPRESSIONS}, ensure_ascii=False),
                 400_000, 88_000)
        resp = wclient.get(f"/brands/{brand_id}/intake/scan/progress?run=1", follow_redirects=False)
        check("W2 ?run=1 執行初掃 -> 303 到 W3", resp.status_code == 303)

        # W3：初掃結果（花費是真實 token 成本：usage × 費率 = 4.20）
        resp = wclient.get(f"/brands/{brand_id}/intake/scan")
        check("W3 GET .../scan -> 200", resp.status_code == 200)
        check("W3 花費列顯示初掃花費 $ 4.20（由 llm_task.cost 即時累計）", "$ 4.20" in resp.text)
        check("W3 初步印象區沿用待確認視覺（同一份 pending-block CSS）", "pending-block" in resp.text)

        # W4：引導問答，5 題全部回答（每一題都由 AI 出題：進度頁 ?run=1 產生下一題）
        for i in range(5):
            q = intake_script.QUESTIONS[i]
            _fake_ai(json.dumps({"done": False, "question": q["question"],
                                  "suggested": {"label": q["suggested"]["label"],
                                                 "desc": q["suggested"]["desc"]},
                                  "branches": [{"label": b["label"], "desc": b["desc"]}
                                               for b in q["branches"]]}, ensure_ascii=False),
                     100_000, 40_000)
            wclient.get(f"/brands/{brand_id}/intake/question/progress?run=1", follow_redirects=False)
            resp = wclient.get(f"/brands/{brand_id}/intake/question")
            check(f"W4 第 {i + 1} 題 GET -> 200", resp.status_code == 200 and q["question"] in resp.text)
            resp = wclient.post(f"/brands/{brand_id}/intake/question",
                                 data={"action": "answer", "choice": "suggested", "note": ""},
                                 follow_redirects=False)
            check(f"W4 第 {i + 1} 題 POST -> 303", resp.status_code == 303)
        # 答完五題後選「跳過這一步」＝不再請 AI 出題（不另花錢）
        wclient.get(f"/brands/{brand_id}/intake/question/skip", follow_redirects=False)
        resp = wclient.get(f"/brands/{brand_id}/intake/question")
        check("W4 五題答完後累計花費 $ 11.70（4.20 + 5×1.50）", "$ 11.70" in resp.text)
        check("W4 結束問答後顯示「沒有需要再問的問題了」", "沒有需要再問的問題了" in resp.text)

        # W5：交接包
        resp = wclient.get(f"/brands/{brand_id}/intake/handoff")
        check("W5 GET .../handoff -> 200", resp.status_code == 200)
        resp = wclient.post(f"/brands/{brand_id}/intake/handoff", data={"depth": "standard"}, follow_redirects=False)
        check("W5 POST -> 303（產生交接包）", resp.status_code == 303)
        resp = wclient.get(f"/brands/{brand_id}/intake/handoff")
        check("W5 產生後花費不變（$ 11.70）", "$ 11.70" in resp.text)
        check("W5 出現 Prompt 複製區", "【品牌】" in resp.text)

        # W6／W7：操作卡
        resp = wclient.get(f"/brands/{brand_id}/intake/handoff/claude")
        check("W6 GET Claude 操作卡 -> 200", resp.status_code == 200)
        check("W6 一個品牌開一個全新對話（R9，非收合）", "一個品牌開一個全新對話" in resp.text
              and "<details" not in resp.text.split("一個品牌開一個全新對話")[0].split("warn-box")[-1])
        resp = wclient.get(f"/brands/{brand_id}/intake/handoff/chatgpt")
        check("W7 GET ChatGPT 操作卡 -> 200", resp.status_code == 200)
        check("W7 一個品牌開一個全新對話（R9）", "一個品牌開一個全新對話" in resp.text)

        # W8：貼回 —— 先送有 3 個錯誤的樣本，確認免費驗證是真的在跑
        resp = wclient.get(f"/brands/{brand_id}/intake/paste")
        check("W8 GET .../paste -> 200", resp.status_code == 200)
        resp = wclient.post(f"/brands/{brand_id}/intake/paste",
                             data={"action": "validate", "raw_text": intake_script.PASTE_SAMPLE_ERRORS},
                             follow_redirects=False)
        check("W8 貼回錯誤樣本 POST -> 303（PRG 回貼回頁）", resp.status_code == 303)
        resp = wclient.get(f"/brands/{brand_id}/intake/paste")
        check("W8 三個錯誤各自標明第幾列", "第 7 列" in resp.text and "第 12 列" in resp.text and "第 19 列" in resp.text)
        check("W8「請 AI 幫我整理格式」按鈕文字含金額",
              "請 AI 幫我整理格式（預估 $ 0.50）" in resp.text)

        # 再貼一次「成功樣本」（24 列，符合 §19.6）。適用範圍驗證只認「已建立的產品」，
        # 樣本裡的產品要先真的建立起來（Mock 時代的 known_products 預載已移除）。
        repo.create_product(main_module.conn, brand_id, name=intake_script.MOCK_PRODUCT_NAME,
                             actor="精靈測試員")
        resp = wclient.post(f"/brands/{brand_id}/intake/paste",
                             data={"action": "validate", "raw_text": intake_script.PASTE_SAMPLE_SUCCESS},
                             follow_redirects=False)
        check("W8 貼回成功樣本 -> 303 到 W9", resp.status_code == 303 and "/intake/review" in resp.headers["location"])

        # W9：AI 帶回的內容
        resp = wclient.get(f"/brands/{brand_id}/intake/review")
        check("W9 GET .../review -> 200", resp.status_code == 200)
        check("W9 顯示 24 筆、全部待確認", "（24 筆" in resp.text and "全部待確認" in resp.text)
        _forbidden_batch_words = ["全部確認", "一鍵確認", "一鍵匯入", "批次確認", "批次接受", "Bulk", "bulk"]
        for tok in _forbidden_batch_words:
            check(f"W9 找不到批次接受字樣「{tok}」（R5 鐵律）", tok not in resp.text)

        # W10：逐條處理——決策 0013 用戶優先：欄位可編輯、不強制證實來源、確認人自動記錄
        resp = wclient.get(f"/brands/{brand_id}/intake/review/20")
        check("W10 第 20 筆 GET -> 200", resp.status_code == 200)
        check("W10 欄位可直接編輯（有內容輸入框）", 'name="content"' in resp.text)
        check("W10 確認人由系統自動記錄（不再要求填寫）", 'name="confirmed_by"' not in resp.text)
        for tok in _forbidden_batch_words:
            check(f"W10 找不到批次接受字樣「{tok}」（R5 鐵律）", tok not in resp.text)

        before_claim_ids = {c["id"] for c in repo.list_claims_for_brand(main_module.conn, brand_id)}
        resp = wclient.post(f"/brands/{brand_id}/intake/review/20", data={
            "action": "confirm", "title": "單一產區直送，附產地標示",
            "content": "每包茶葉包裝上都印有茶園產地與採收季節，可追溯到單一茶園。",
            "category": "可用", "scope": "整個品牌",
        }, follow_redirects=False)
        check("W10 宣稱不填證實來源也能「確認」-> 303（決策 0013 不擋）", resp.status_code == 303)
        after_claims_list = repo.list_claims_for_brand(main_module.conn, brand_id)
        check("W10「確認」真的寫進 repository（宣稱數 +1）", len(after_claims_list) == len(before_claim_ids) + 1)
        new_claim = next(c for c in after_claims_list if c["id"] not in before_claim_ids)
        # 第 20 筆的標題是「單一產區直送，附產地標示」；內容是解釋佐證脈絡的說明文字，
        # 不是宣稱語句本身——claim_text 應該是標題，不是那段說明。
        check("W10 宣稱出口 claim_text 是宣稱語句本身（不是說明文字）",
              new_claim["claim_text"] == "單一產區直送，附產地標示")
        new_claim_source = repo.get_source_reference(main_module.conn, brand_id,
                                                       new_claim["evidence_source_reference_id"])
        check("W10 宣稱的說明文字保留在 source_reference.note（沒有硬塞進 claim_text）",
              new_claim_source is not None and "可追溯到單一茶園" in (new_claim_source["note"] or ""))

        resp = wclient.get(f"/brands/{brand_id}/intake/review/1")
        check("W10 第 1 筆（品牌事實）GET -> 200", resp.status_code == 200)
        before_pending = len(repo.list_brand_facts(main_module.conn, brand_id, status="pending"))
        resp = wclient.post(f"/brands/{brand_id}/intake/review/1",
                             data={"action": "pending", "title": "單一產區直送定位",
                                   "content": "主打單一產區的烏龍與紅茶，價格帶中高。",
                                   "category": "定位", "scope": "整個品牌"}, follow_redirects=False)
        check("W10「先存成待確認」-> 303", resp.status_code == 303)
        after_pending = len(repo.list_brand_facts(main_module.conn, brand_id, status="pending"))
        check("W10「先存成待確認」真的寫進 repository（待確認品牌事實數 +1）",
              after_pending == before_pending + 1)

        resp = wclient.get(f"/brands/{brand_id}/hub/facts")
        check("確認出口寫入後，品牌智庫的品牌事實子頁看得到", "已確認" in resp.text and "待確認" in resp.text)

        # W11：花費上限設定 —— 低於已花費金額要擋下來
        resp = wclient.get(f"/brands/{brand_id}/intake/budget")
        check("W11 GET .../budget -> 200", resp.status_code == 200)
        resp = wclient.post(f"/brands/{brand_id}/intake/budget",
                             data={"limit": "1", "next": f"/brands/{brand_id}"})
        check("W11 上限低於已花費 -> 400", resp.status_code == 400)
        check("W11 錯誤訊息帶實際已花費金額", "11.70" in resp.text)

        # 花費列三種門檻狀態（一般／接近上限／已達上限）
        resp = wclient.get(f"/brands/{brand_id}/intake/handoff")
        check("花費列一般狀態（cost-meter-normal）", "cost-meter-normal" in resp.text)
        wclient.post(f"/brands/{brand_id}/intake/budget",
                      data={"limit": "13", "next": f"/brands/{brand_id}/intake/handoff"})
        resp = wclient.get(f"/brands/{brand_id}/intake/handoff")
        check("花費列接近上限狀態（cost-meter-near，累計 11.70／上限 13 = 90%）", "cost-meter-near" in resp.text)
        check("接近上限文字本身講出狀況（不只靠顏色）", "快到上限了" in resp.text)

        # W12：超限攔截——上限調回 12（已花 11.70），下一步（貼回修復預估 $0.50）會超過 -> 在呼叫前攔下
        wclient.post(f"/brands/{brand_id}/intake/budget",
                      data={"limit": "12", "next": f"/brands/{brand_id}/intake/paste"})
        wclient.post(f"/brands/{brand_id}/intake/paste",
                     data={"action": "validate", "raw_text": intake_script.PASTE_SAMPLE_ERRORS})
        resp = wclient.post(f"/brands/{brand_id}/intake/paste", data={"action": "fix", "raw_text": ""},
                             follow_redirects=False)
        check("W12：格式修復先進進度頁 -> 303", resp.status_code == 303
              and resp.headers["location"].endswith("/intake/paste/progress"))
        resp = wclient.get(f"/brands/{brand_id}/intake/paste/progress", follow_redirects=False)
        check("W12：下一步預估會超過上限 -> 303 到 .../intake/limit（呼叫前攔截）",
              resp.status_code == 303 and "/intake/limit?kind=paste" in resp.headers["location"])
        resp = wclient.get(f"/brands/{brand_id}/intake/limit?kind=paste")
        check("W12 GET .../limit -> 200", resp.status_code == 200)
        check("W12 花費數字沒有因為被攔截而增加（仍是 11.70）", "$ 11.70" in resp.text)
        check("W12 三個出口都在（提高上限／不再花錢／先離開）",
              "把上限提高到" in resp.text and "不再花錢" in resp.text and "先離開，之後再繼續" in resp.text)
        resp = wclient.get(f"/brands/{brand_id}/intake/limit/skip-to-handoff", follow_redirects=False)
        check("W12「不再花錢，用目前的結果直接去交接包」正常導到交接包頁",
              resp.status_code == 303 and resp.headers["location"].endswith("/intake/handoff"))

        # 草稿續接（§19.3）：品牌總覽列出「建檔進行中」、品牌檔案頁 banner，關閉後重整再出現
        resp = wclient.get("/")
        check("品牌總覽顯示「建檔進行中・繼續建檔」", "建檔進行中" in resp.text and "繼續建檔" in resp.text)
        resp = wclient.get(f"/brands/{brand_id}")
        check("品牌檔案頁顯示續接 banner", "引導建檔還沒完成" in resp.text)
        resp = wclient.get(f"/brands/{brand_id}?continue_dismissed=1")
        check("按「知道了」關閉後續接 banner 消失（本次瀏覽）", "引導建檔還沒完成" not in resp.text)
        resp = wclient.get(f"/brands/{brand_id}")
        check("重新整理（乾淨網址）banner 再次出現，草稿仍在", "引導建檔還沒完成" in resp.text)

        # 草稿真的落地 DB：重開連線（等同重啟伺服器）後草稿還在、進度沒掉
        main_module.reopen_connection()
        resp = wclient.get("/")
        check("重啟連線後品牌總覽仍顯示「建檔進行中」（草稿存 intake_draft，非記憶體）",
              "建檔進行中" in resp.text)
        d_after = intake_state.get_draft(brand_id)
        check("重啟連線後草稿花費與步驟都還原（11.70、第 5 步）",
              d_after is not None and abs(d_after["cost_spent"] - 11.70) < 1e-9 and d_after["step"] == 5)

        # 品牌總覽既有的示範品牌 C（小滿製茶）也是預先種好、進行中的草稿（§14.3）
        c_draft_brand = next(b for b in repo.list_brands(main_module.conn) if "小滿製茶" in b["name"])
        c_draft = intake_state.get_draft(c_draft_brand["id"])
        check("示範品牌 C 有預先種好的建檔草稿（第 3 步、已花 $7.20）",
              c_draft is not None and c_draft["step"] == 3 and c_draft["cost_spent"] == 7.20)

    check_intake_wizard()

    # 尚未設定操作人時，需要 actor 的 POST 要轉址去 /settings/operator（而不是落到 500 錯誤頁）。
    # 用獨立、沒有 cookie 的 client，確認的是「完全沒設過操作人」這個情境。
    anon_client = TestClient(main_module.app)
    resp = anon_client.post("/brands/new", data={"name": "無操作人測試品牌", "client_name": ""},
                             follow_redirects=False)
    check("無操作人時 POST /brands/new -> 303", resp.status_code == 303)
    check("無操作人時轉址到 /settings/operator",
          resp.headers.get("location", "").startswith("/settings/operator"))

    # 先走真正的「設定操作人」流程：後面所有新增／確認操作都需要 actor 才能落地。
    resp = client.post("/settings/operator", data={"name": "測試員", "next": "/"}, follow_redirects=False)
    check("POST 設定操作人 -> 303", resp.status_code == 303)

    brands = repo.list_brands(main_module.conn, status="active")
    brand_a = next(b for b in brands if "青原生活" in b["name"])
    brand_b = next(b for b in brands if "森野工坊" in b["name"])
    brand_a_id, brand_a_name = brand_a["id"], brand_a["name"]
    brand_b_id, brand_b_name = brand_b["id"], brand_b["name"]
    product_a1_id = repo.list_products(main_module.conn, brand_a_id)[0]["id"]

    # -- 1. 主要路由回 200 --------------------------------------------------
    get_routes = [
        "/",
        "/brands/new",
        f"/brands/{brand_a_id}",
        f"/brands/{brand_a_id}/edit",
        f"/brands/{brand_a_id}/hub",
        f"/brands/{brand_a_id}/hub/facts",
        f"/brands/{brand_a_id}/hub/rules",
        f"/brands/{brand_a_id}/hub/claims",
        f"/brands/{brand_a_id}/hub/products",
        f"/brands/{brand_a_id}/hub/assets",
        f"/brands/{brand_a_id}/hub/channels",
        f"/brands/{brand_a_id}/hub/customer-voice",
        f"/brands/{brand_a_id}/customer-voice/new",
        f"/brands/{brand_a_id}/customer-voice/guide",
        f"/brands/{brand_a_id}/facts/new",
        f"/brands/{brand_a_id}/products/new",
        f"/brands/{brand_a_id}/products/{product_a1_id}",
        f"/brands/{brand_a_id}/products/{product_a1_id}/facts",
        f"/brands/{brand_a_id}/products/{product_a1_id}/economics-view",
        f"/brands/{brand_a_id}/products/{product_a1_id}/rules",
        f"/brands/{brand_a_id}/products/{product_a1_id}/claims",
        f"/brands/{brand_a_id}/products/{product_a1_id}/facts/new",
        f"/brands/{brand_a_id}/products/{product_a1_id}/economics",
        f"/brands/{brand_a_id}/products/{product_a1_id}/handoff",
        f"/brands/{brand_a_id}/rules/new",
        f"/brands/{brand_a_id}/claims/new",
        f"/brands/{brand_a_id}/channels/new",
        f"/brands/{brand_b_id}",
        "/settings/operator",
    ]
    for path in get_routes:
        resp = client.get(path)
        check(f"GET {path} -> 200", resp.status_code == 200)

    # 待確認事實的確認頁（需要抓一個真實 id）
    pending_fact = repo.list_brand_facts(main_module.conn, brand_a_id, status="pending")[0]
    resp = client.get(f"/brands/{brand_a_id}/facts/{pending_fact['id']}/confirm")
    check("GET 品牌事實確認頁 -> 200", resp.status_code == 200)

    # -- 2. 品牌隔離：切到品牌 B 後畫面上沒有品牌 A 名稱 -----------------------
    # 注意：header 的品牌切換器（<details> 收合清單）依規格必須列出「所有使用中品牌」
    # 供使用者切換，因此品牌 A 名稱合法出現在該收合清單裡；隔離要驗證的是「主內容區」
    # （<main>…</main>，即 5 個分區實際顯示的資料）不得出現其他品牌的任何字串。
    def main_content(html: str) -> str:
        start = html.find("<main")
        end = html.find("</main>")
        return html[start:end] if start != -1 and end != -1 else html

    resp = client.get(f"/brands/{brand_b_id}?switched=1")
    check("GET 品牌 B 功能選單頁 -> 200", resp.status_code == 200)
    check("切到品牌 B 後主內容區不含品牌 A 名稱", brand_a_name not in main_content(resp.text))
    check("切到品牌 B 後畫面含切換提示", "已切換到" in resp.text and brand_b_name in resp.text)
    check("品牌 B（全空）不顯示待確認提醒卡", "pending-alert-card" not in resp.text)

    resp = client.get(f"/brands/{brand_b_id}/hub/facts")
    check("GET 品牌 B 品牌智庫的品牌事實子頁 -> 200", resp.status_code == 200)
    check("品牌 B（全空）顯示空狀態文字", "還沒有已確認的品牌事實" in resp.text)
    check("品牌 B 待確認分區整塊不出現（無琥珀待確認說明）", "這些內容還沒被確認" not in resp.text)

    # 跨品牌存取：品牌 A 的產品掛在品牌 B 底下 -> 一律「找不到」，不得洩漏歸屬
    resp = client.get(f"/brands/{brand_b_id}/products/{product_a1_id}")
    check("跨品牌存取產品 -> 404", resp.status_code == 404)
    check("跨品牌存取顯示「找不到」而非洩漏品牌歸屬", "找不到這個產品" in resp.text and "屬於" not in resp.text)

    # 不存在的品牌 -> 404，不噴 500 / 不出現原始例外
    resp = client.get("/brands/not-a-real-brand")
    check("不存在的品牌 -> 404", resp.status_code == 404)
    check("404 頁面文字為「找不到這個品牌」", "找不到這個品牌" in resp.text)

    # -- 3a. 新增品牌 POST 流程 ----------------------------------------------
    resp = client.post("/brands/new", data={"name": "測試示範品牌（示範資料）", "client_name": "測試客戶"},
                        follow_redirects=False)
    check("POST 新增品牌 -> 303", resp.status_code == 303)
    location = resp.headers.get("location", "")
    check("新增品牌轉址帶成功訊息", "kind=ok" in location and "msg=" in location)
    resp2 = client.get(location)
    check("新增品牌轉址後頁面 200", resp2.status_code == 200)
    check("新增品牌成功訊息含品牌名稱", "已新增品牌" in resp2.text and "測試示範品牌" in resp2.text)

    new_brand = next(b for b in repo.list_brands(main_module.conn) if b["name"] == "測試示範品牌（示範資料）")
    new_brand_id = new_brand["id"]

    # 新增品牌表單驗證失敗：必填缺漏 -> 400，且原輸入保留
    resp = client.post("/brands/new", data={"name": "", "client_name": "只填這格"})
    check("新增品牌缺必填 -> 400", resp.status_code == 400)
    check("新增品牌錯誤訊息不提示狀態碼", "400" not in resp.text)
    check("新增品牌錯誤時原輸入保留（所屬客戶）", "只填這格" in resp.text)

    # -- 3b. 新增品牌事實 + 確認事實 POST 流程 -------------------------------
    resp = client.post(f"/brands/{new_brand_id}/facts/new", data={
        "fact_type": "positioning", "label": "測試事實標題", "value": "這是一段測試用的事實內容，長度足夠檢查排版與回填是否正常運作。",
        "status": "pending", "source_reference": "",
    }, follow_redirects=False)
    check("POST 新增品牌事實 -> 303", resp.status_code == 303)
    resp2 = client.get(resp.headers["location"])
    check("新增事實後品牌檔案頁 200", resp2.status_code == 200)
    check("新增事實成功訊息含事實名稱", "測試事實標題" in resp2.text and "待確認" in resp2.text)

    new_fact = next(f for f in repo.list_brand_facts(main_module.conn, new_brand_id)
                     if f["label"] == "測試事實標題")
    check("新事實狀態確實為 pending", new_fact["status"] == "pending")

    resp = client.post(f"/brands/{new_brand_id}/facts/{new_fact['id']}/confirm",
                        data={"confirmed_by": "測試員"}, follow_redirects=False)
    check("POST 確認事實 -> 303", resp.status_code == 303)
    resp2 = client.get(resp.headers["location"])
    check("確認後品牌檔案頁 200", resp2.status_code == 200)
    check("確認成功訊息含確認人姓名", "已確認" in resp2.text and "測試員" in resp2.text)
    new_fact_after = repo.get_brand_fact(main_module.conn, new_brand_id, new_fact["id"])
    check("事實真的轉為已確認", new_fact_after["status"] == "confirmed" and new_fact_after["confirmed_by"] == "測試員")

    # 確認事實缺必填確認人 -> 400，且保留在確認頁
    resp = client.post(f"/brands/{brand_a_id}/facts/{pending_fact['id']}/confirm", data={"confirmed_by": ""})
    check("確認事實缺確認人 -> 400", resp.status_code == 400)
    pending_fact_after = repo.get_brand_fact(main_module.conn, brand_a_id, pending_fact["id"])
    check("確認事實仍是 pending（未被誤確認）", pending_fact_after["status"] == "pending")

    # -- 3c. 三欄同時驗證失敗（新增品牌事實：類型／名稱／內容全空） -------------
    resp = client.post(f"/brands/{new_brand_id}/facts/new", data={
        "fact_type": "", "label": "", "value": "", "status": "pending", "source_reference": "",
    })
    check("三欄同時空白 -> 400", resp.status_code == 400)
    check("錯誤摘要顯示 3 個欄位", "有 3 個欄位需要修正" in resp.text)

    # -- 3d. 新增產品 -> 直接進產品檔案頁 ------------------------------------
    resp = client.post(f"/brands/{new_brand_id}/products/new", data={"name": "測試產品（示範資料）"},
                        follow_redirects=False)
    check("POST 新增產品 -> 303", resp.status_code == 303)
    resp2 = client.get(resp.headers["location"])
    check("新增產品後落在產品檔案頁", "測試產品（示範資料）" in resp2.text)

    # -- 3e. 產品經濟數字：售價非數字 -> 錯誤訊息含範例，不出現狀態碼 ---------
    resp = client.post(f"/brands/{brand_a_id}/products/{product_a1_id}/economics", data={
        "selling_price": "abc", "fixed_cost": "", "unit_variable_cost": "", "shipping_cost": "",
        "currency": "TWD", "cpa_roas_basis": "", "effective_from": "", "confirmed_by": "小陳",
    })
    check("售價非數字 -> 400", resp.status_code == 400)
    check("售價錯誤訊息帶範例數字", "請填數字" in resp.text)

    # -- 4. 畫面不得出現內部欄位名／狀態英文值（§16 第 8 條，用純文字比對） ----
    def visible_text(html: str) -> str:
        html = re.sub(r"<script[\s\S]*?</script>", " ", html)
        html = re.sub(r"<[^>]+>", " ", html)
        return html

    forbidden_tokens = ["confirmed", "brand_fact", "brd_", "pending"]
    for path in (f"/brands/{brand_a_id}", f"/brands/{brand_a_id}/hub/facts",
                 f"/brands/{brand_a_id}/hub/rules"):
        text_only = visible_text(client.get(path).text)
        for tok in forbidden_tokens:
            check(f"{path} 可見文字不含「{tok}」", tok not in text_only)
        # "hard" 排除英文字母子字串誤判（例如中文旁的 CSS class 不算可見文字，已由 strip tag 處理）
        check(f"{path} 可見文字不含「hard」", "hard" not in text_only)

    resp = client.get(f"/brands/{brand_a_id}/rules/new")
    rules_form_text = visible_text(resp.text)
    check("新增規則表單頁可見文字不含「hard」", "hard" not in rules_form_text)
    check("新增規則表單頁可見文字不含「soft」", "soft" not in rules_form_text)

    # -- 5. 重啟 app 後資料仍在（持久化證明） --------------------------------
    # 關掉現有連線、重新走一次啟動流程（migrations + 備份檢查），再重建 TestClient，
    # 證明剛剛新增的品牌／事實是真的寫進 DB 檔案，不是活在記憶體物件裡。
    main_module.reopen_connection()
    client2 = TestClient(main_module.app)
    resp = client2.get(f"/brands/{new_brand_id}")
    check("重啟後新品牌頁面仍是 200", resp.status_code == 200)
    check("重啟後新品牌資料仍在（品牌名稱）", "測試示範品牌" in resp.text)
    resp = client2.get(f"/brands/{new_brand_id}/hub/facts")
    check("重啟後新品牌資料仍在（事實與確認狀態）",
          "測試事實標題" in resp.text and "已確認" in resp.text)
    resp = client2.get(f"/brands/{brand_a_id}")
    check("重啟後示範品牌資料仍在", brand_a_name in resp.text)

    print()
    if failures:
        print(f"共 {len(failures)} 項失敗：")
        for f in failures:
            print(" -", f)
        return 1
    print("全部通過。")
    return 0


if __name__ == "__main__":
    sys.exit(run())
