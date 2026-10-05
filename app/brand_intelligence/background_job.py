"""app/brand_intelligence/background_job.py — 背景工作通知（純搬家，來源：
`routes_library.py` 的 `_cv_jobs` 與 `routes_products.py` 的 `_research_jobs`，
兩邊原本各自寫了一份「先通知後 commit」，這裡抽成共用）。業務內容（job 內容形狀、
成功／失敗判斷）留在呼叫端，這裡只管通知。

行程內工作狀態表＋背景執行緒那個共用類別，曾經跟這裡共用一份。票 08／09 把最後兩個
呼叫端（`app/intake/routes_api.py` 的 `_JOBS`、`app/intake/persona_generation.py` 的
`JOBS`）搬上 `app.background` 佇列後，全站再也沒有任何呼叫端建構它，這裡跟著把類別本身
刪掉——沒有呼叫端的類別是死代碼，不是「以防萬一」。

對外進入點：`notify()` 函式。
誰依賴它：`app/brand_web/routes_library.py`、`routes_products.py`、`routes_report_api.py`、
`app/intake/routes_api.py`、`app/intake/persona_generation.py`。
"""

from app.brand_intelligence import repository as bi_repo
from app.core import interrupts as core_interrupts


def notify(conn, brand_id: str, *, category: str, dedupe_key: str, message: str, action_url: str) -> None:
    """背景工作完成／失敗時送打斷佇列通知。F50-I07（Contract J，intake #9）：這裡不再截斷
    ——尾巴一刀切下去，長商品名會把「完成」「失敗」一起切掉，兩種通知變得一模一樣。呼叫端用
    `core_interrupts.notice(outcome, subject)` 組句子（結果永遠完整，只縮主題）；超長訊息由
    `core_interrupts.enqueue` 照舊拒收。"""
    brand = bi_repo.get_brand(conn, brand_id)
    assert brand is not None, f"找不到品牌：{brand_id}"
    core_interrupts.enqueue(
        conn, org_id=brand["org_id"], category=category, dedupe_key=dedupe_key,
        brand_id=brand_id, message=message, action_url=action_url,
    )
    conn.commit()
