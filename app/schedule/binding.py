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

from app.meta import repository as meta_repo
from app.schedule import repository as schedule_repo
from app.schedule import tree as tree_mod

NO_TREE_TO_BIND_MESSAGE = "還沒有成功產生的活動樹可以綁定，請先展開活動樹。"
BIND_FAILURE_MESSAGE = "配對失敗，請檢查名稱是否完全相符"

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


def tree_with_bindings(conn, tree_row: dict, org_id: str, brand_id: str) -> dict:
    """票 T3b／T3c（ADR 0055 §4）：疊上 `channel_entity_map` 的綁定，每一層都疊——
    位置（`node_key`）配對，名字不符就顯示未綁定。讀從不寫。"""
    tree = tree_mod.tree_from_task_row(tree_row)
    bindings = schedule_repo.bindings_by_node_key(conn, org_id, brand_id, CHANNEL_KEY)
    _apply_bindings(tree["nodes"], bindings)
    return tree


def bind_tree(conn, tree_row: dict, org_id: str, brand_id: str) -> bool:
    """票 11／T3b／T3c：用名稱精準比對（區分大小寫、不 trim）把活動綁回第一層節點，
    已綁定的跳過；零筆或兩筆以上是失敗，不猜。第一層綁定成功（不論是這次剛綁的、還是
    先前就綁著）之後，才在它底下比對第二層——用它的 `bound_external_id`（活動 id）當
    父層範圍，只在這個活動內部找廣告組合；第一層沒綁成的，底下的第二層整批不比對，
    不猜整個帳號（ADR 0055 §7）。回傳「這一批有沒有任何一個節點配對失敗」，訊息由
    呼叫端貼（整批同一句，不逐節點分開講，ADR 0055 §4）。"""
    tree = tree_with_bindings(conn, tree_row, org_id, brand_id)
    account_ids = meta_repo.bound_account_ids_for_brand(conn, org_id, brand_id)
    channel_id, any_failure, newly_bound = None, False, False

    for node in tree["nodes"]:
        if node["bound_external_id"] is None:
            matches = meta_repo.campaign_ids_by_exact_name(
                conn, org_id, account_ids, node["name"]
            )
            if len(matches) != 1:
                any_failure = True
                continue  # 沒有活動可以當第二層的父層範圍，子節點整批不比對
            channel_id = channel_id or schedule_repo.ensure_meta_channel(conn, org_id)
            schedule_repo.upsert_binding(
                conn, org_id=org_id, brand_id=brand_id, channel_id=channel_id,
                node_key=node["node_key"], node_name_at_bind=node["name"],
                external_id=matches[0]["campaign_id"],
                external_status=matches[0]["external_status"],
            )
            newly_bound = True
            node["bound_external_id"] = matches[0]["campaign_id"]

        for child in node["children"]:
            if child["bound_external_id"] is not None:
                continue
            matches = meta_repo.ad_set_ids_by_exact_name(
                conn, org_id, node["bound_external_id"], child["name"]
            )
            if len(matches) != 1:
                any_failure = True
                continue
            channel_id = channel_id or schedule_repo.ensure_meta_channel(conn, org_id)
            schedule_repo.upsert_binding(
                conn, org_id=org_id, brand_id=brand_id, channel_id=channel_id,
                node_key=child["node_key"], node_name_at_bind=child["name"],
                external_id=matches[0]["adset_id"],
                external_status=matches[0]["external_status"],
            )
            newly_bound = True

    if newly_bound:
        conn.commit()
    return any_failure
