"""app/schedule/binding.py — 把活動樹的節點對應到平台上真的存在的實體（票 T3c 站①）。

Private to app/schedule/（集裝箱憲章第一節）：只有同套件內的 `routes.py`／`jobs.py` 呼叫，
外面任何模組都不 import 這個檔案。

**為什麼從 `routes.py` 搬出來**（2026-09-03 使用者批准，模組邊界＝憲法規則 9）：
`app/schedule/` 底下的分工是「`routes.py` 收 HTTP 請求，`plan.py`／`tree.py`／`creative.py`／
`period.py` 做事」。綁定比對是做事——它讀平台清單、寫 `channel_entity_map`、決定什麼算配對
成功，跟 HTTP 一點關係都沒有。搬家的觸發點是 `routes.py` 剛好卡在 800 行的機器上限、
T3c 一行都加不進去，但**行數只是叫醒鈴，不是理由**——工作流規範逐字寫著「行數永遠不該
下令拆檔，拆不拆是模組邊界的決定」，所以這裡記的是邊界的理由，不是行數。

搬家本身不改任何行為：既有測試全綠就是它的證明。
"""

import app.shared.web as web
from app.meta import repository as meta_repo
from app.schedule import period_repository as period_repo
from app.schedule import repository as schedule_repo
from app.schedule import tree as tree_mod

NO_TREE_TO_BIND_MESSAGE = "還沒有成功產生的活動樹可以綁定，請先展開活動樹。"

# 票 05（plan-quality）：使用者 2026-09-08 裁決——樹一律照 `budget_level` 分配，實際預算
# 掛在哪一層是讀 Meta 才知道的事，不寫進任何表。兩層都是平台自己叫的名字
# （`tree["levels"]`），不是我們發明的詞彙。
BUDGET_LEVEL_NOTE = (
    "你的預算掛在「{actual}」這一層，這棵樹是照「{expected}」那一層分配的；核准的比例不會"
    "在 Meta 上生效，這一期每個{expected}花多少由 Meta 自己決定。"
)


def bind_failure_message(failures: list[str]) -> str:
    """把逐節點的失敗原因組成一句話。

    2026-09-04 實機驗收：原本整批共用一句「配對失敗，請檢查名稱是否完全相符」（ADR 0055 §4
    的「不逐節點分開講」），在真的失敗當下沒有下一步——它沒說是哪一個名稱對不上，也沒說
    Meta 那邊是找不到、還是找到兩個同名的。這兩種要做的事完全相反：找不到是去 Meta 建、
    或把名字改成一字不差；找到兩個是去 Meta 把重複的改名。**只講「有失敗」等於沒講。**

    仍然保留「一次講完整批」這件事（不是每個節點各跳一個錯誤），ADR 0055 §4 要的是這個。"""
    # 去重保序：同一份方案裡兩個節點可以取一樣的名字，那會產生兩句一模一樣的原因
    # （`test_two_depth_two_siblings_same_name_both_stay_unbound` 就是這個形狀）。
    # 兩個節點都沒綁上這件事不因為訊息合併而改變，重複講一次只是雜訊。
    return (
        "配對失敗："
        + "、".join(dict.fromkeys(failures))
        + "。名稱要一字不差（區分大小寫，前後空白也算）。"
        "上一層沒有配對成功時，它底下的節點這次不會比對。"
    )

# 這個模組目前只認得 Meta 一個通路。通路轉接層是 T4 的事（ADR 0055 §8：綁定的「動作」是
# 平台專屬的，通用的是 `channel_entity_map` 那張表，不是這段程式）。
CHANNEL_KEY = "meta"


def _apply_bindings(nodes: list, bindings: dict) -> None:
    """疊上 `channel_entity_map` 的綁定，遞迴每一層——位置（`node_key`）配對，名字不符
    就顯示未綁定，同一條規則套用到每一個深度（票 T3c，ADR 0055 §4：舊版只疊第一層，
    第二層寫進去的綁定沒有這段就永遠只在資料庫裡看得到）。"""
    for node in nodes:
        if (b := bindings.get(node["node_key"])) and b["node_name_at_bind"] == node["name"]:
            node["bound_external_id"] = b["external_id"]
        _apply_bindings(node["children"], bindings)


def _continuity_map(conn, org_id: str, brand_id: str) -> dict:
    """票 04：最近一次已結算檔期的逐節點記分列，轉成 `(depth, node_name) -> node_key`——
    `tree_with_bindings()` 疊 `continued_from_node_key` 用的查表。跟判決無關（`win`／`lose`／
    `unclear` 都在表裡；哪些名字「該」沿用是 `jobs._continuity_text()` 那段 prompt 的事，
    這裡純粹是「這一期的名字，對不對得上上一期記過分的某個節點」）。沒有已結算檔期或零筆
    記分列 → 空字典（每個節點都疊 `None`）。只查一次（ticket §2「Read the results once per
    call」）。"""
    period = period_repo.latest_settled_period(conn, org_id, brand_id)
    if period is None:
        return {}
    results = period_repo.period_node_results(conn, org_id, brand_id, period["id"])
    return {(r["depth"], r["node_name"]): r["node_key"] for r in results}


def _apply_continuity(nodes: list, depth: int, continuity: dict) -> None:
    """遞迴每一層疊 `continued_from_node_key`——第一層（`depth == 1`）從來沒被記過分，
    一律 `None`；第二、三層照 `(depth, name)` 查表，查不到一樣是 `None`。"""
    for node in nodes:
        node["continued_from_node_key"] = (
            None if depth == 1 else continuity.get((depth, node["name"]))
        )
        _apply_continuity(node["children"], depth + 1, continuity)


def tree_with_bindings(conn, tree_row: dict, org_id: str, brand_id: str) -> dict:
    """票 T3b／T3c（ADR 0055 §4）：疊上 `channel_entity_map` 的綁定，每一層都疊——
    位置（`node_key`）配對，名字不符就顯示未綁定。票 04：再疊一層讀時 overlay——
    `continued_from_node_key`，跟綁定完全獨立的另一件事（綁定認 `node_key`，這個認
    `(depth, name)`；一個節點可以「延續」但因為換了位置還沒綁定，反之亦然，ADR 0064）。
    讀從不寫。"""
    tree = tree_mod.tree_from_task_row(tree_row)
    bindings = schedule_repo.bindings_by_node_key(conn, org_id, brand_id, CHANNEL_KEY)
    _apply_bindings(tree["nodes"], bindings)
    continuity = _continuity_map(conn, org_id, brand_id)
    _apply_continuity(tree["nodes"], 1, continuity)
    return tree


def _failure_reason(name: str, matches: list) -> str:
    """0 筆與 2 筆以上要分開講——使用者要做的事相反（去建／去改名 vs 去把重複的改名）。"""
    if not matches:
        return f"「{name}」在 Meta 上找不到"
    return f"「{name}」在 Meta 上有 {len(matches)} 個同名的"


def bind_tree(conn, tree_row: dict, org_id: str, brand_id: str) -> list[str]:
    """票 11／T3b／T3c／T5／10：用名稱精準比對（區分大小寫、不 trim）把活動綁回第一層節點，
    已綁定的跳過；零筆或兩筆以上是失敗，不猜。第一層綁定成功（不論是這次剛綁的、還是
    先前就綁著）之後，才在它底下比對第二層——用它的 `bound_external_id`（活動 id）當
    父層範圍，只在這個活動內部找廣告組合；第一層沒綁成的，底下的第二層整批不比對，
    不猜整個帳號（ADR 0055 §7）。第二層（廣告組合）綁定成功之後，同一條規則再套一次
    深一層：第三層（廣告，ADR 0055 §7 留給這張票開）在它底下比對，只在這個廣告組合
    內部找廣告；第二層沒綁成的，底下的第三層整批不比對。回傳「這一批有哪些節點配對失敗、
    各自是哪一種失敗」，空清單＝整批成功；組句子的是呼叫端（`bind_failure_message()`，
    仍然一次講完整批，ADR 0055 §4）。

    票 10（ADR 0064 §3）：「這個節點已經綁了嗎」問的是 `bindings_for_tree(...,
    tree_row["id"])`——**這一棵樹自己**有沒有這個節點的列，不是疊圖用的
    `tree_with_bindings()`（那支回答「這個位置現在顯示成綁定了嗎」，會被上一棵樹留下的
    列騙到：同位置、同名字，疊圖照樣顯示綁定，但那一列的 `source_tree_task_id` 是上一棵
    樹的，不是這一棵）。用這個顯示疊圖判斷會不會去重綁，這一棵樹的廣告就永遠拿不到屬於
    自己的綁定列——ticket 從另一邊重新引進的那個 bug。這裡因此不重用 `tree_with_bindings()`
    的輸出，改用 `tree_mod.tree_from_task_row()` 純取樹形，`bound_external_id` 一律從本地
    的 `bound` 字典查（先看這一棵樹是不是已經綁過，沒有才去 Meta 配對）。"""
    tree = tree_mod.tree_from_task_row(tree_row)
    bound = schedule_repo.bindings_for_tree(
        conn, org_id, brand_id, CHANNEL_KEY, tree_row["id"]
    )
    account_ids = meta_repo.bound_account_ids_for_brand(conn, org_id, brand_id)
    # 票 T3e（ADR 0055 §11）：深度 2（扛預算）節點綁定成功時，順手記一列
    # `period_node_membership`——「品牌當下的檔期」用模組既有的同一條讀
    # （`period_repo.get_latest_period`），不是另開一條。沒有檔期（這個品牌從沒出過
    # 方案就直接綁定，理論上不會發生，但不是不可能）就不寫、也不算失敗——寫在這裡，不是
    # 悄悄跳過沒人知道。深度 3（廣告）不寫 membership——那張表只認扛預算的那一層
    # （ADR 0055 §6），第三層再寫一列會讓 node_level_spend() 在兩層都算到同一筆錢。
    period = period_repo.get_latest_period(conn, org_id, brand_id)
    channel_id, newly_bound = None, False
    failures: list[str] = []

    for node in tree["nodes"]:
        existing = bound.get(node["node_key"])
        node_bound_id = existing["external_id"] if existing else None
        if node_bound_id is None:
            matches = meta_repo.campaign_ids_by_exact_name(
                conn, org_id, account_ids, node["name"]
            )
            if len(matches) != 1:
                failures.append(_failure_reason(node["name"], matches))
                continue  # 沒有活動可以當第二層的父層範圍，子節點整批不比對
            channel_id = channel_id or schedule_repo.ensure_meta_channel(conn, org_id)
            schedule_repo.upsert_binding(
                conn, org_id=org_id, brand_id=brand_id, channel_id=channel_id,
                node_key=node["node_key"], node_name_at_bind=node["name"],
                external_id=matches[0]["campaign_id"],
                external_status=matches[0]["external_status"],
                source_tree_task_id=tree_row["id"],
            )
            newly_bound = True
            node_bound_id = matches[0]["campaign_id"]

        for child in node["children"]:
            existing_child = bound.get(child["node_key"])
            child_bound_id = existing_child["external_id"] if existing_child else None
            if child_bound_id is None:
                matches = meta_repo.ad_set_ids_by_exact_name(
                    conn, org_id, node_bound_id, child["name"]
                )
                if len(matches) != 1:
                    failures.append(_failure_reason(child["name"], matches))
                    continue  # 沒有廣告組合可以當第三層的父層範圍，孫節點整批不比對
                channel_id = channel_id or schedule_repo.ensure_meta_channel(conn, org_id)
                schedule_repo.upsert_binding(
                    conn, org_id=org_id, brand_id=brand_id, channel_id=channel_id,
                    node_key=child["node_key"], node_name_at_bind=child["name"],
                    external_id=matches[0]["adset_id"],
                    external_status=matches[0]["external_status"],
                    source_tree_task_id=tree_row["id"],
                )
                if period is not None:
                    schedule_repo.insert_period_node_membership(
                        conn, org_id=org_id, brand_id=brand_id,
                        campaign_period_id=period["id"], channel_id=channel_id,
                        node_key=child["node_key"],
                        from_date=period["start_date"], to_date=period["end_date"],
                        source_tree_task_id=tree_row["id"],
                    )
                newly_bound = True
                child_bound_id = matches[0]["adset_id"]

            for grandchild in child["children"]:
                if bound.get(grandchild["node_key"]) is not None:
                    continue
                matches = meta_repo.ad_ids_by_exact_name(
                    conn, org_id, child_bound_id, grandchild["name"]
                )
                if len(matches) != 1:
                    failures.append(_failure_reason(grandchild["name"], matches))
                    continue
                channel_id = channel_id or schedule_repo.ensure_meta_channel(conn, org_id)
                schedule_repo.upsert_binding(
                    conn, org_id=org_id, brand_id=brand_id, channel_id=channel_id,
                    node_key=grandchild["node_key"], node_name_at_bind=grandchild["name"],
                    external_id=matches[0]["ad_id"],
                    external_status=matches[0]["external_status"],
                    source_tree_task_id=tree_row["id"],
                )
                newly_bound = True

    if newly_bound:
        conn.commit()
    return failures


def budget_placement_note(conn, org_id: str, brand_id: str, tree_row: dict) -> str | None:

    """票 05：這棵樹以為預算在 `budget_level` 那一層，Meta 上實際掛在哪一層——讀兩次都不
    落地（每次呼叫都重新問 Meta），使用者 2026-09-08 裁決：提示，不擋流程。

    只看深度 1／2 的綁定（Meta 廣告，深度 3，從不扛預算）。沒有樹、樹失敗、或沒有
    `budget_level`；`expected` 那一層一個綁定都沒有；讀 Meta 失敗（`web.ApiError`，這個
    提示是錦上添花，不該讓剛成功的綁定被一次無關的讀取拖累）；或兩層都沒讀到預算——
    一律回 `None`（沒東西可比、或比不出來，就不講）。`expected` 那一層自己就有預算 →
    位置吻合，也回 `None`；只有「另一層」有預算，才是這則提示要講的事。"""
    tree = tree_mod.tree_from_task_row(tree_row)
    expected = tree["budget_level"]
    if tree["failure"] is not None or expected is None or expected not in (1, 2):
        return None  # 深度 3（廣告）不扛預算，這裡沒有可比的綁定，比照「沒東西可比」

    bound = schedule_repo.bindings_for_tree(conn, org_id, brand_id, CHANNEL_KEY, tree_row["id"])
    ids_by_depth: dict[int, list[str]] = {1: [], 2: []}
    for node_key, row in bound.items():
        depth = node_key.count(".") + 1
        if depth in ids_by_depth:
            ids_by_depth[depth].append(row["external_id"])

    expected_ids = ids_by_depth[expected]
    if not expected_ids:
        return None
    other = 1 if expected == 2 else 2
    other_ids = ids_by_depth[other]

    try:
        budgets = meta_repo.budgets_for_bound_ids(conn, org_id, expected_ids + other_ids)
    except web.ApiError:
        return None

    def has_budget(external_id: str) -> bool:
        entry = budgets.get(external_id) or {}
        return bool(entry.get("daily_budget")) or bool(entry.get("lifetime_budget"))

    if any(has_budget(i) for i in expected_ids):
        return None  # 位置吻合
    if any(has_budget(i) for i in other_ids):
        return BUDGET_LEVEL_NOTE.format(
            actual=tree["levels"][other - 1], expected=tree["levels"][expected - 1]
        )
    return None  # 兩層都沒讀到預算，看不出來，不亂講
