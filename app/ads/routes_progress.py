# -*- coding: utf-8 -*-
"""app/ads/routes_progress.py — 背景進度引擎（T4 廣告模組 Jinja 大清倉第 2 刀刪掉
`_render_wait_page`：所有等待頁呼叫端——`routes_plan.py::ads_plan_progress`、
`routes_performance.py::ads_reading_progress`、`routes_sync.py` 的 Meta／GA4 回填
精靈——都已被對應 /api 端點取代並隨之刪除，見 routes.py 檔頭。本檔現在只剩背景
執行緒引擎本身，供仍在用同一套機制的 /api 端點（routes_campaigns_open_api.py 的
plan/generate＋plan/status、routes_tracking_api.py、routes_weekly_proposals_api.py）
呼叫。

用 brand_id/cycle_id 當 key 記一份「目前在哪一階段、狀態、結果」的模組級 dict：
  - status="waiting"：呼叫端記錄過一次「開始等」，但還沒真的觸發生成。
  - status="running"：背景執行緒已經在跑（冪等閘：同一個 key 只會有一個 running 執行緒，
    _progress_start 用鎖判斷「查已有 entry」與「啟動執行緒」這組合是原子的）。
  - status="done"：執行緒跑完，result=(ok, err) 待下一次請求消化並清除。

`app.ads.routes`（匯總檔）在自己模組頂端 `from app.ads.routes_progress import ...`
把這裡的名字原樣接回去，讓既有 `from app.ads import routes as ads_routes` 再
`ads_routes._progress_key(...)` 這套跨檔慣例、以及測試對 `ads_routes._PROGRESS_
TIMEOUT_SECONDS` 之類的模組級屬性覆寫（test_ads_progress_background.py、
test_ads_plan_status_json_api.py）繼續原樣可用——名字在哪個模組被 import 進去，
屬性覆寫／dict 內容互動都是同一份物件，不受影響。一律 `ads_routes.` 開頭即時查值，
不得改成 `from app.ads.routes_progress import X` 靜態綁死（同 orders_channel 那組
注入變數的先例，理由見 app/ads/routes.py 檔頭）。

ponytail: _progress_state 的讀寫多數是單一鍵賦值（CPython 原子），只有「判斷 key 是否
已在跑、要不要啟動新執行緒」這個複合動作真的需要鎖，其餘沿用單純 dict。
"""

import threading
import time

_progress_state: dict = {}
_progress_lock = threading.Lock()

# 首版寫死的合理初值（決策 0023 第 9 條修訂）；之後可換成近幾次實測生成耗時的統計範圍。
_USUAL_RANGE = {"plan": "30 到 60 秒", "creative": "40 到 90 秒", "ga4": "5 到 20 秒",
                "meta_backfill": "1 到 3 分鐘", "ga4_backfill": "30 秒到 2 分鐘"}

# 與 DESIGN.md §19.4 規則 6「逾時 90 秒視為失敗」對齊：等待頁不再無限等下去；背景執行緒
# 若真的還在跑（例如撞到 llm/gateway.py 的 120 秒逾時＋一次重試），就讓它安靜跑完，
# 結果寫進一個已經被使用者放棄、之後不會再被讀到的 entry（見 _progress_run 的 None 檢查）。
_PROGRESS_TIMEOUT_SECONDS = 90


def _progress_key(kind: str, brand_id: str, cycle_id: str) -> str:
    return f"{kind}:{brand_id}:{cycle_id}"


def _progress_touch(key: str, stages: list) -> dict:
    """使用者看到等待頁，但還沒觸發生成：第一次碰到這個 key 才記開始時間，已經有紀錄
    （不管是 waiting／running／done）就沿用，不重置——已等秒數才不會被重刷歸零。"""
    with _progress_lock:
        return _progress_state.setdefault(
            key, {"stage": stages[0][0], "started_at": time.time(),
                 "status": "waiting", "result": None})


def _progress_start(key: str, stages: list, work) -> dict:
    """冪等啟動背景生成：同一個 key 已經在跑（running）或已經跑完還沒被消化（done）就
    原樣回傳，不重新啟動執行緒——這是 F5／多分頁重整不會重複打付費 API 的關鍵。

    work 是一個 zero-arg callable：`work(on_stage) -> (ok, err)`，實際呼叫哪個 generate
    函式由呼叫端決定（薄殼：這裡不認識任何一種生成流程的細節）。

    B0-28 根因修復：`status == "failed"`（逾時被 `_progress_fail()` 判定失敗）不代表背景
    執行緒真的停了——Python 執行緒殺不掉，它可能還在等 LLM 回應。這裡先看
    `entry["thread"].is_alive()`：還活著就安靜接回同一條執行緒（不重打一次付費 API，
    只是把狀態改回 running 繼續等它自然跑完，讓真正的結果事後寫得回來，不是打第二次
    造成雙重扣款）；真的已經停了（例如意外死掉、從沒寫回結果）才視同 `waiting`、放心
    重開一條新的。
    """
    with _progress_lock:
        entry = _progress_state.get(key)
        if entry is None:
            entry = {"stage": stages[0][0], "started_at": time.time(),
                     "status": "running", "result": None, "thread": None}
            _progress_state[key] = entry
            should_start = True
        elif entry["status"] == "waiting":
            entry["status"] = "running"
            should_start = True
        elif entry["status"] == "failed" and entry.get("thread") is not None and entry["thread"].is_alive():
            # 只接回執行緒，不重打 API——但逾時判定是看 started_at 到現在過了多久，不重設
            # 這個時間戳，下一次輪詢會發現「還是超過門檻」，立刻又判一次失敗，使用者永遠等
            # 不到這條還活著的執行緒真正跑完（本行不重設就會反紅：見對應測試）。
            entry["status"] = "running"
            entry["started_at"] = time.time()
            should_start = False
        elif entry["status"] == "failed":
            entry.update({"stage": stages[0][0], "started_at": time.time(),
                          "status": "running", "result": None})
            should_start = True
        else:
            should_start = False  # running 或 done：已經有一份在跑／跑完了，冪等略過
    if should_start:
        thread = threading.Thread(target=_progress_run, args=(key, work), daemon=True)
        entry["thread"] = thread
        thread.start()
    return entry


def _progress_run(key: str, work) -> None:
    """背景執行緒實際跑的函式：不假設 work() 回傳值的形狀（plan/creative 回 (ok, err)
    二元組，ga4_sync 回一個 SyncResult 物件，各自語意由呼叫端自己拆），一律包成
    `("ok", 原始回傳值)`；連 work() 本身都爆例外這種非預期狀況才是 `("error", 人話錯誤)`
    ——不吞成靜默失敗（鐵則 6：一切可追溯，至少要讓下一個請求看到「背景執行發生未預期錯誤」）。
    """
    try:
        result = work(lambda s: _progress_set_stage(key, s))
        outcome = ("ok", result)
    except Exception as exc:  # noqa: BLE001 — 背景執行緒的最後一道防線，不能讓例外憑空消失
        outcome = ("error", f"背景執行發生未預期錯誤：{exc}")
    entry = _progress_state.get(key)
    # entry 可能已經被一支全新的 _progress_start() 換掉（使用者逾時後重試，且這支舊執行緒
    # 那時已經死了）——那種情況這支「屬於舊執行緒」的結果不該蓋掉新的一份，安靜結束即可
    # （B0-28：能安全分辨新舊靠的是 _progress_start 只在舊執行緒真的死透才會蓋 entry）。
    if entry is not None and entry.get("thread") in (None, threading.current_thread()):
        entry["status"] = "done"
        entry["result"] = outcome


def _progress_set_stage(key: str, stage: str) -> None:
    entry = _progress_state.get(key)
    if entry is not None:
        entry["stage"] = stage


def _progress_clear(key: str) -> None:
    _progress_state.pop(key, None)


def _progress_fail(key: str, message: str) -> None:
    """逾時判定失敗（B0-28 根因修復）：把 entry 標成終局的 `failed`，不是 `_progress_clear()`
    整個拔掉。背景執行緒殺不掉，逾時當下它可能還在等 LLM 回應——原本清掉 entry 會讓
    `_progress_run()` 事後真正跑完時找不到地方寫結果，安靜把已經花錢做出來的成果丟掉
    （下一次讀狀態又變回「entry 不存在＝done」的假象，使用者看到的是「done 但沒內容」，
    零錯誤訊息；重按一次又真的多打一次付費 API＝雙重扣款，這正是 B0-28 的兩個症狀）。

    留著 entry 讓 `_progress_run()` 之後還找得到地方寫真正的結果（見該函式），也讓使用者
    不管重整幾次都看到同一句失敗訊息，而不是下一次問就悄悄變成看似正常的『done』。
    `_progress_start()` 看到 `status == "failed"` 時，靠 `entry["thread"].is_alive()`
    判斷要不要真的重打一次生成，還是安靜接回這條還在跑的舊執行緒（同檔案該函式docstring）。
    """
    entry = _progress_state.get(key)
    if entry is not None:
        entry["status"] = "failed"
        entry["result"] = ("error", message)


def _progress_definition_rows(stages: list, kind: str, entry: dict) -> list:
    """組出等待頁要的清單：每個實際階段一列（完成／進行中／還沒開始），
    最後加一列「已等 X 秒／通常範圍 Y」——沒有任何百分比或假進度條。"""
    seen_current = False
    rows = []
    for key, label in stages:
        if key == entry["stage"]:
            state, seen_current = "進行中", True
        elif seen_current:
            state = "還沒開始"
        else:
            state = "完成"
        rows.append((label, state, False))
    elapsed = max(0, int(time.time() - entry["started_at"]))
    rows.append(("已等", f"{elapsed} 秒／通常範圍 {_USUAL_RANGE[kind]}", False))
    return rows
