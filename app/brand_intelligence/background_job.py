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
    """背景工作完成／失敗時送打斷佇列通知；超過卡片字數上限就截斷
    （`core_interrupts.enqueue` 對超長訊息會直接 raise，兩邊呼叫端原本都是各自截斷）。"""
    if len(message) > core_interrupts.MAX_MESSAGE_LEN:
        message = message[: core_interrupts.MAX_MESSAGE_LEN]
    brand = bi_repo.get_brand(conn, brand_id)
    assert brand is not None, f"找不到品牌：{brand_id}"
    core_interrupts.enqueue(
        conn, org_id=brand["org_id"], category=category, dedupe_key=dedupe_key,
        brand_id=brand_id, message=message, action_url=action_url,
    )
    conn.commit()
