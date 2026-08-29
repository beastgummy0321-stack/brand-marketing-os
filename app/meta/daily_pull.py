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

Fix round (review reject on done-check "a scheduled pull runs unattended"): `_dispatch_daily_pull`
below is a procrastinate `periodic()` task that fires once a day and defers one
`background.meta_daily_pull` job per org with a bound account — same fan-out the `__main__`
block below already did by hand. It only *fires* because app/background.start_worker() now
keeps a worker running inside the same uvicorn process this ticket's earlier round said had
none (see app/background/__init__.py docstring for why that isn't a new deployment shape).
The manual path stays first-class either way: `uv run python -m app.meta.daily_pull` still
works exactly as before, consistent with 手動路徑永遠一級公民.
"""

from datetime import UTC, datetime

from app.background import app as background_app
from app.core.db import connection
from app.meta import graph
from app.meta import repository as repo

_TASK_NAME = "background.meta_daily_pull"
_DISPATCH_TASK_NAME = "meta.daily_pull_dispatch"
_DISPATCH_PERIODIC_ID = "meta_daily_pull"
_DAILY_PULL_CRON = "0 3 * * *"  # 每天觸發一次；伺服器本機時間，未特別做時區換算——單機
                                 # 部署跑在使用者自己機器上，多晚幾小時拉不影響「今天有拉到」


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


def _dispatch_daily_pull(timestamp: int) -> None:
    """procrastinate periodic task body：一天觸發一次，對每個至少綁了一個 Meta 帳號的組織
    各 defer 一個 `background.meta_daily_pull` job——跟本檔 `__main__` 手動路徑做的事一模
    一樣，差別只在誰按下開始鍵（見檔頭 fix round 說明）。

    不掛 "background." 前綴：這支本身沒有單一 org_id 可帶（一次觸發要跑遍所有組織），跟
    `TaskSignatureOrgIdGateTest` 要求的「處理一個組織的 handler」是不同性質的兩支——它是
    排程器，不是 handler，故意落在那道只掃 "background." 開頭任務的閘門範圍之外，不是為了
    閃掉檢查而改名（"meta." 前綴標的正是它仍然只碰 app/meta 自己的東西）。
    """
    with connection() as conn:
        org_ids = repo.orgs_with_bound_accounts(conn)
    a = background_app()
    for org_id in org_ids:
        a.configure_task(_TASK_NAME).defer(org_id=org_id)


def register_task() -> None:
    """掛 procrastinate task，冪等（可以呼叫任意次）——見本檔檔頭「為什麼不能只做一次」。
    連同掛上每日排程的 periodic dispatch task（票 05 fix round）。"""
    a = background_app()
    if _TASK_NAME not in a.tasks:
        a.task(name=_TASK_NAME)(run_daily_pull)
    if _DISPATCH_TASK_NAME not in a.tasks:
        a.periodic(cron=_DAILY_PULL_CRON, periodic_id=_DISPATCH_PERIODIC_ID)(
            a.task(name=_DISPATCH_TASK_NAME)(_dispatch_daily_pull)
        )


if __name__ == "__main__":
    # 手動觸發今天的拉取：`uv run python -m app.meta.daily_pull`。
    #
    # 這支是「手動路徑」本身，不是權宜替代品——正常情況下不需要人手動跑，app/main.py
    # 啟動時已經把 uvicorn 這個 process 掛成常駐 worker，每天會自己跑
    # `_dispatch_daily_pull`（見檔頭 fix round 說明）。這支腳本留著給想立刻補拉、或伺服器
    # 沒開著的時候用：對每個至少綁了一個 Meta 帳號的組織各 defer 一個 job，跑一次 worker
    # 把它們都處理掉，然後結束，符合 手動路徑永遠一級公民。
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
