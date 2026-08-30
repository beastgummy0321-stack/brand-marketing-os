"""app/meta/daily_pull.py — the actual pull-and-store work for ticket 05, private to this
package (only app/meta/__init__.py exports anything from here, container contract §1).

`run_daily_pull(org_id)` is the procrastinate task body. It lives here, not in
app/background, because a module never reads/writes another module's tables (container
contract) — the Graph API call and the meta_ad_account/meta_entity_spend writes belong
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

票 S1：拉取從「今天、只有 campaign 一層」變成「三層都拉」，並且長出 `backfill()`——一個
組織＋帳號範圍的日期區間補拉，按日曆月切段、走同一支 upsert。它是 ADR 0039 那個洞（機器
沒開的日子沒有人補）的修補路徑，也是接手既有帳號的載入路徑（GRILL 決策 9）。
"""

import calendar
from datetime import date, timedelta

from app.background import app as background_app
from app.core import settings as coresettings
from app.core.db import connection
from app.meta import graph
from app.meta import repository as repo

_TASK_NAME = "background.meta_daily_pull"
_DISPATCH_TASK_NAME = "meta.daily_pull_dispatch"
_DISPATCH_PERIODIC_ID = "meta_daily_pull"
_DAILY_PULL_CRON = "0 3 * * *"  # 每天觸發一次；伺服器本機時間，未特別做時區換算——單機
                                 # 部署跑在使用者自己機器上，多晚幾小時拉不影響「今天有拉到」。
                                 # 票 04-1b 之後，被拉的「哪一天」已經改用組織時區
                                 # （_pull_one_account），所以觸發時刻早晚不再決定日期標籤；
                                 # 觸發時刻本身的時區處理仍是上雲前的債（BOARD.md 小債）。

# 三層一起拉，順序固定 campaign→adset→ad（票 S1，GRILL 決策 1）：錢分在 level 2 的 adset
# 預算，數字卻只有 level 1 的話，計畫寫的「70% 主打／30% 測試」事後永遠對不起來——那不是
# 少一個功能，是一個學不會的迴圈。
_LEVELS = ("campaign", "adset", "ad")

# Meta 只保留 37 個月的 insights：
# "The start date of the time range cannot be beyond 37 months from the current date"
# —— https://developers.facebook.com/docs/marketing-api/reference/ad-account/insights/
# （2026-08-30 查證，SPEC §7.4(a)）。這是平台事實不是偏好，所以擋在程式裡。
# 陷阱：這 37 個月只屬於「不帶任何 breakdown、也不要 reach」的查詢——一加就掉到 13 個月，
# 而且 Meta 不報錯、只是少給資料。同一段警告也寫在 graph.py 的欄位清單旁邊，因為那裡才是
# 有人會手癢多加一個欄位的地方。
_RETENTION_MONTHS = 37


def _pull_one_account(conn, org_id: str, token: str, account: dict) -> None:
    """抓一個帳號『今天』三個層級的 insights，各自 upsert 進 meta_entity_spend；
    **三個層級全部成功才** mark_pull_succeeded。

    為什麼半套不算成功：`last_pull_at` 是畫面上「資料新到什麼時候」的唯一依據
    （`repository.last_pull_at` 刻意取一批帳號的 min，就是為了誠實顯示最舊的那份），
    campaign 拉到了、ad 層 GraphError 了卻蓋上今天的時間戳，等於對使用者宣告三層數字都是
    今天的——半套的拉取謊報成完整，比整包失敗更危險，因為它看起來像資料。

    已經寫進去的 campaign／adset 列不回滾：它們是真的，重跑會被 upsert 覆蓋（唯一索引在
    資料庫，見 `repository.upsert_entity_spend`）。這個帳號的「上次成功」就停在上一次真的
    三層都拉到的時刻，畫面照實顯示資料舊了。一個帳號失敗不影響其他帳號：迴圈由呼叫端做，
    這裡只管一個帳號（票 05 done-check 不變）。

    「今天」是這個組織所在時區的今天（票 04-1b），不是伺服器的今天——這個日期同時是跟
    Meta 要哪一天的 insights、以及那筆花費記在哪一天，兩邊都不能跟著機器搬家。但
    `spend_date` 不是從這裡的 today 寫進資料庫：每一列用 Meta 自己回的 `date_start`（票 S1
    D7）。今天的拉取兩者相同，補拉時一次回應橫跨好幾天，只有 `date_start` 是對的。"""
    today = coresettings.today_for_org(conn, org_id=org_id)
    for level in _LEVELS:
        rows = graph.list_entity_insights(token, account["account_id"], level, today, today)
        repo.upsert_entity_spend(conn, org_id, account["id"], rows)
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


def _earliest_pullable(today: date) -> date:
    """今天往回推 37 個月的同一天；那個月沒有這一天就取當月最後一天（3/31 → 2/28）。

    純日期算術，不碰網路也不碰資料庫，所以 `backfill` 的保護可以在任何 HTTP 呼叫之前就
    下判斷（票 S1 done-check 7）。"""
    total = today.year * 12 + (today.month - 1) - _RETENTION_MONTHS
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(today.day, calendar.monthrange(year, month)[1]))


def _month_chunks(since: date, until: date) -> list[tuple[date, date]]:
    """把 [since, until]（含頭含尾）切成一段一個日曆月；頭尾兩段夾在呼叫端給的日期上，
    不擴張成整個月——補 6/15~8/20 就是補這 67 天，不會順手把 6/1~6/14 也拉進來。

    為什麼按月切：官方對「查詢太大／逾時」的處方是把日期範圍切小，不是改用 async job
    （SPEC §7.4(b)，原文 "try to break down the query into smaller queries by putting in
    filters like date range"）。用日曆月而不是「每 30 天」，是因為人講的補拉單位是月份
    ——出事時「六月那個月沒拉到」比「第 3 段沒拉到」好查。

    純函式，所以「三個月的範圍剛好切三段」可以單獨測（票 S1 done-check 8）。"""
    chunks: list[tuple[date, date]] = []
    start = since
    while start <= until:
        first_of_next = date(start.year + start.month // 12, start.month % 12 + 1, 1)
        end = min(first_of_next - timedelta(days=1), until)
        chunks.append((start, end))
        start = end + timedelta(days=1)
    return chunks


def backfill(org_id: str, since: date, until: date) -> int:
    """把 [since, until] 這段日子的三層 insights 補回來，回傳寫進去的列數。

    給誰用：ADR 0039 的 worker 跟著網站行程跑，機器關著的那幾天沒有人補——這支就是那個
    補法；同時也是「接手一個已經投過廣告的帳號」的載入路徑（GRILL 決策 9，P7：先不做
    畫面，CLI 就是入口）。

    `since`／`until` **兩個都必填、沒有預設值**（票 S1 D5），CLI 也強制要 `--since`。
    「要往回讀多久」是偏好不是常數，而且它不能做成 rule card：`app/core/rule_cards.py`
    的 `get_value` 是**品牌層**（收 `brand_id`），補拉卻是**組織＋廣告帳戶層**——一個廣告
    帳戶可以服務好幾個品牌（`brand_meta_ad_account` 是 m:n，見 repository.py 檔頭）。拿
    品牌層的偏好去決定組織層的拉取，是用一個誠實回答不了這個問題的東西當預設值——所以
    這裡沒有預設值，日期由開口要補拉的人講明。

    不呼叫 `mark_pull_succeeded`：`last_pull_at` 的意思是「今天的數字新到什麼時候」，
    補完去年六月不會讓今天的數字變新（同 `_pull_one_account` 那條誠實標準）。

    錯誤往外丟，不逐帳號吞掉：`run_daily_pull` 吞是因為沒有人在看，這支是人手動跑的，
    錯誤要當場看見（CLI 接住印人話，見 `__main__`）。每一段拉完就 commit，所以跑到一半
    斷掉，已經補進去的月份留著；重跑同一個指令安全（唯一索引 upsert，覆蓋不重複）。

    `graph.fetch_page` 的 `timeout=10.0` **維持不動**：ad 層一整個月要花多久，今天沒有
    任何實測數字，沒有量過就不准動那個數字（票 S1 D9）。"""
    with connection() as conn:
        if until < since:
            raise ValueError(f"補拉的起日 {since} 比迄日 {until} 還晚，這段日期是空的。")
        # 這道檢查在任何 HTTP 呼叫之前（today 與 token 都只讀資料庫）。丟 ValueError 不丟
        # graph.GraphError：Meta 根本沒被問過，用 GraphError 會讓訊息說謊，而且
        # run_daily_pull 那種「except graph.GraphError: continue」的寫法會把一個打錯的
        # 日期悄悄吞掉。參數檢查丟 ValueError 是既有慣例
        # （app/brand_intelligence/repository.py 的 set_brand_switches）。
        earliest = _earliest_pullable(coresettings.today_for_org(conn, org_id=org_id))
        if since < earliest:
            raise ValueError(
                f"Meta 只保留最近 {_RETENTION_MONTHS} 個月的成效資料"
                "（developers.facebook.com/docs/marketing-api/reference/ad-account/"
                f"insights/），{since} 已經超過了，最早只能從 {earliest} 開始補拉。"
            )
        token = repo.get_token(conn, org_id)
        if token is None:
            return 0  # 這個組織還沒接 Meta 權杖，沒有東西可補（比照 run_daily_pull）
        written = 0
        for account in repo.list_bound_accounts(conn, org_id):
            for level in _LEVELS:
                for chunk_since, chunk_until in _month_chunks(since, until):
                    rows = graph.list_entity_insights(
                        token, account["account_id"], level, chunk_since, chunk_until
                    )
                    repo.upsert_entity_spend(conn, org_id, account["id"], rows)
                    conn.commit()  # 一段一存：斷在第九個月，前八個月留著
                    written += len(rows)
        return written


if __name__ == "__main__":
    # 手動路徑本身（憲法規則 6：手動路徑永遠一級公民），兩種用法：
    #   uv run python -m app.meta.daily_pull                     → 拉「今天」，行為同票 05
    #   uv run python -m app.meta.daily_pull --since 2026-06-01  → 補拉，三層都補
    #
    # 不帶參數這條完全沒變：對每個至少綁了一個 Meta 帳號的組織各 defer 一個 job，跑一次
    # worker 把它們處理掉然後結束。正常情況下不需要人手動跑（app/main.py 啟動時已經把
    # uvicorn 這個 process 掛成常駐 worker），這支留給想立刻補拉、或伺服器沒開的時候用。
    #
    # `import app.main` 除了觸發完整組裝（含 register_task()），也是 `.env` 被讀進環境
    # 變數的地方（app/main.py `_load_dotenv()`）——兩條路徑都需要，所以留在最前面。
    import argparse

    import app.main  # noqa: F401 — 觸發完整的 app 組裝與 .env 載入，不需要 app 物件本身

    def _iso_date(text: str) -> date:
        try:
            return date.fromisoformat(text)
        except ValueError:
            raise argparse.ArgumentTypeError("日期要寫成 YYYY-MM-DD，例如 2026-06-01。") from None

    _parser = argparse.ArgumentParser(
        prog="python -m app.meta.daily_pull",
        description="不帶參數＝拉今天；帶 --since＝補拉一段日期（campaign／adset／ad 三層都拉）。",
    )
    _parser.add_argument(
        "--since", type=_iso_date, metavar="YYYY-MM-DD",
        help="補拉的起日（含當天）。要補拉就一定要給——往回讀多久是偏好，程式不猜。",
    )
    _parser.add_argument(
        "--until", type=_iso_date, metavar="YYYY-MM-DD",
        help="補拉的迄日（含當天）；不給就補到各組織自己時區的今天。",
    )
    _args = _parser.parse_args()

    register_task()
    with connection() as _conn:
        _org_ids = repo.orgs_with_bound_accounts(_conn)
        # --until 沒給就用「各組織自己時區的今天」——這不是被禁的那種預設值：被禁的是
        # 「往回讀多久」（那是偏好，見 backfill 檔頭），而「補到今天為止」是資料的盡頭。
        _until_by_org = {} if _args.since is None else {
            o: _args.until or coresettings.today_for_org(_conn, org_id=o) for o in _org_ids
        }
    if not _org_ids:
        print("沒有任何組織綁定 Meta 廣告帳戶，沒有東西可拉。")
    elif _args.since is not None:
        for _org_id in _org_ids:
            _until = _until_by_org[_org_id]
            try:
                _n = backfill(_org_id, _args.since, _until)
            except (ValueError, graph.GraphError) as _exc:
                # 一個組織補不動不該讓其他組織也停掉；已經 commit 的月份留著，修好之後
                # 重跑同一個指令會覆蓋補齊。印人話，不吐 traceback、也不靜默跳過。
                print(f"組織 {_org_id}：補拉沒有完成——{_exc}")
                continue
            print(f"組織 {_org_id}：{_args.since} ~ {_until} 補拉完成，寫入 {_n} 列。")
    else:
        _a = background_app()
        with _a.open():
            for _org_id in _org_ids:
                _a.configure_task(_TASK_NAME).defer(org_id=_org_id)
        _a.run_worker(wait=False)
        print(f"已對 {len(_org_ids)} 個組織排入今天的 Meta 花費拉取。")
