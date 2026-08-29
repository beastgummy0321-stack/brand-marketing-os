"""app/meta/daily_pull.py — the actual pull-and-store work for ticket 05, private to this
package (only app/meta/__init__.py exports anything from here, container contract §1).

`run_daily_pull(org_id)` is the procrastinate task body. It lives here, not in
app/background, because a module never reads/writes another module's tables (container
contract) — the Graph API call and the meta_ad_account/meta_campaign_spend writes belong
to app/meta. `register_task()` does a plain top-level `from app.background import app`
(forward dependency, LAYER_ORDER already allows app.meta → app.background) rather than
the reverse, which would be an upward violation app/background must never take.

`register_task()` must be callable any number of times, idempotently, against whatever
`background.app()` currently is: that App object gets rebuilt whenever `db.dsn()` changes
(app/background/__init__.py's docstring — this is what makes every test module's own
Postgres schema work), so registering once at import time would silently stop applying
after any DSN change. app/main.py calls it once after the router-registration loop; a test
that gets a fresh `background.app()` for its own schema calls it again right after, same
pattern app/tests/test_background.py already establishes for the App itself.

Scope, deliberately: this ticket registers the task and proves it runs correctly through
procrastinate (defer → run_worker(wait=False) → rows land, same shape as ticket 01's own
test). It does not add a persistent worker process or a procrastinate `periodic()` cron —
nothing in this deployment runs a worker continuously today (confirmed: 啟動行銷系統.bat
only starts uvicorn), and deciding to add one is a deployment-shape change CLAUDE.md's
rule 9 asks be proposed and approved before it's built, not slipped in as a side effect of
a ticket about the pull-and-store logic. Until that decision is made, the manual path
stays first-class: this task can be deferred and run by hand (a small script + Windows
Task Scheduler, or a person triggering it), consistent with 手動路徑永遠一級公民.
"""

from datetime import UTC, datetime

from app.background import app as background_app
from app.core.db import connection
from app.meta import graph
from app.meta import repository as repo

_TASK_NAME = "background.meta_daily_pull"


def _pull_one_account(conn, org_id: str, token: str, account: dict) -> None:
    """抓一個帳號『今天』的每檔活動 insights，upsert 進 meta_campaign_spend，只有成功
    才更新 last_pull_at——GraphError 就直接放掉這個帳號，舊資料原封不動（票 05
    done-check：失敗的拉取不覆蓋好資料，且看得出上次成功是什麼時候）。一個帳號失敗
    不影響其他帳號：迴圈由呼叫端做，這裡只管一個帳號。"""
    today = datetime.now(UTC).date()
    rows = graph.list_campaign_insights(token, account["account_id"], today)
    repo.upsert_campaign_spend(conn, org_id, account["id"], today, rows)
    repo.mark_pull_succeeded(conn, org_id, account["id"])


def run_daily_pull(org_id: str) -> None:
    """procrastinate task body。每一句 SQL 都帶 org_id——一個組織的 run 不寫另一個組織
    的列（ADR 0038、票 05 done-check）。`org_id` 是必要參數，滿足 ADR 0038「這份 ADR
    欠的閘門」（app/tests/test_background.py TaskSignatureOrgIdGateTest，任務名以
    "background." 開頭才會被那道閘門掃到——這裡就是這樣命名的）。"""
    with connection() as conn:
        token = repo.get_token(conn, org_id)
        if token is None:
            return  # 這個組織還沒接 Meta 權杖，沒有東西可拉
        for account in repo.list_bound_accounts(conn, org_id):
            try:
                _pull_one_account(conn, org_id, token, account)
            except graph.GraphError:
                continue  # 這個帳號這次失敗，換下一個；舊資料留著，見上方 docstring


def register_task() -> None:
    """掛 procrastinate task，冪等（可以呼叫任意次）——見本檔檔頭「為什麼不能只做一次」。"""
    a = background_app()
    if _TASK_NAME not in a.tasks:
        a.task(name=_TASK_NAME)(run_daily_pull)


if __name__ == "__main__":
    # 手動觸發今天的拉取：`uv run python -m app.meta.daily_pull`。
    #
    # 沒有持續運行的 worker 程序（見檔頭「Scope，刻意」）——這支就是「手動路徑」本身，
    # 不是它的權宜替代品：對每個至少綁了一個 Meta 帳號的組織各 defer 一個 job，跑一次
    # worker 把它們都處理掉，然後結束。今天可以人手執行；要不要每天自動叫這支腳本
    # （Windows 工作排程器，或未來 SaaS 部署自己的排程器），跟要不要換成常駐 worker
    # 是同一個部署形態的決定，CLAUDE.md 規則 9 要求先提計畫、等批准，這裡不擅自做。
    import app.main  # noqa: F401 — 觸發完整的 app 組裝（含 register_task()），不需要 app 物件本身

    register_task()
    with connection() as _conn:
        _org_ids = repo.orgs_with_bound_accounts(_conn)
    if not _org_ids:
        print("沒有任何組織綁定 Meta 廣告帳戶，沒有東西可拉。")
    else:
        _a = background_app()
        with _a.open():
            for _org_id in _org_ids:
                _a.configure_task(_TASK_NAME).defer(org_id=_org_id)
        _a.run_worker(wait=False)
        print(f"已對 {len(_org_ids)} 個組織排入今天的 Meta 花費拉取。")
