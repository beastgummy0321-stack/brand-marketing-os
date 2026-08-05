# -*- coding: utf-8 -*-
"""app/tools/real_db_probe.py — 拿真實資料庫的複本做驗證，原檔一律不動。

為什麼需要這支：全新 migrate 出來的資料庫，跟一路 migration 疊上來的真實庫**不是同一個
東西**。實際踩過兩次：
  1. 真實庫的 learning_ledger 帶著 REFERENCES campaign_cycle 外鍵，全新庫沒有。
  2. 刪產品時 creative_brief -> experiment_cell 懸空、整個刪除失敗——五路查驗全在全新庫
     上跑，一致得出「產品層沒有跨模組外鍵」，在他們的環境是對的，在正式環境是錯的。

所以動到刪除流程或 schema 的改動，驗收要跑這支，不能只靠 pytest 的暫存資料庫。

用法（都只讀原檔、只寫複本）：
    python -m app.tools.real_db_probe schema           # 真實庫 schema vs 全新庫，列出差異
    python -m app.tools.real_db_probe list             # 列出品牌與產品，供挑對象
    python -m app.tools.real_db_probe delete-brand   <brand_id>
    python -m app.tools.real_db_probe delete-product <brand_id> <product_id>

安全：複本放暫存目錄；跑之前把 ANTHROPIC_API_KEY 設成假值，任何誤呼叫都打不出去。
"""

import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_DB = REPO_ROOT / "data" / "app.db"


def _tables(conn) -> list:
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def _fks(conn, table) -> set:
    return {(r[3], r[2], r[4] or "id") for r in conn.execute(f"PRAGMA foreign_key_list({table})")}


def _cols(conn, table) -> set:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _open_copy():
    """把真實庫複製到暫存目錄，回傳 (複本路徑, 暫存目錄)。原檔全程唯讀。"""
    if not REAL_DB.exists():
        sys.exit(f"找不到真實資料庫：{REAL_DB}（這支工具要有它才跑得起來）")
    tmp = Path(tempfile.mkdtemp(prefix="real_db_probe_"))
    copy = tmp / "copy.db"
    shutil.copy2(REAL_DB, copy)
    return copy, tmp


def _boot(copy: Path, tmp: Path):
    """把 app 指到複本上開起來。必須在 import app.main 之前設好環境變數。"""
    os.environ["BRAND_OS_DB"] = str(copy)
    os.environ["BRAND_OS_BACKUP_DIR"] = str(tmp / "backups")
    os.environ["BRAND_OS_UPLOADS"] = str(tmp / "uploads")
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-FAKE-DO-NOT-CALL"
    sys.path.insert(0, str(REPO_ROOT))
    import app.main as main  # noqa: E402  環境變數設好才能 import
    return main


def schema_diffs() -> list:
    """真實庫 schema vs 全新 migrate 的庫，回傳差異描述列。差異＝pytest 看不到的死角。

    抽成純函式給 app/tests/test_real_db_schema_drift.py 用：冒出新的差異要自動變紅，
    不必等有人想到要手動跑這支工具。
    """
    copy, tmp = _open_copy()
    fresh_dir = Path(tempfile.mkdtemp(prefix="fresh_db_"))
    sys.path.insert(0, str(REPO_ROOT))
    from app.core import db  # noqa: E402
    fresh = db.connect_and_migrate(fresh_dir / "fresh.db")
    real = sqlite3.connect(copy)

    rt, ft = set(_tables(real)), set(_tables(fresh))
    diffs = []
    for t in sorted(rt - ft):
        diffs.append(f"只有真實庫有這張表：{t}（全新庫不會建，測試永遠看不到）")
    for t in sorted(ft - rt):
        diffs.append(f"只有全新庫有這張表：{t}（真實庫還沒 migrate 到）")
    for t in sorted(rt & ft):
        rc, fc = _cols(real, t), _cols(fresh, t)
        for c in sorted(rc - fc):
            diffs.append(f"{t}.{c}：只有真實庫有這個欄位")
        for c in sorted(fc - rc):
            diffs.append(f"{t}.{c}：只有全新庫有這個欄位")
        rf, ff = _fks(real, t), _fks(fresh, t)
        for col, parent, pcol in sorted(rf - ff):
            diffs.append(f"{t}.{col} -> {parent}.{pcol}：**只有真實庫有這條外鍵**"
                         f"（全新庫上的測試驗不到它）")
        for col, parent, pcol in sorted(ff - rf):
            diffs.append(f"{t}.{col} -> {parent}.{pcol}：只有全新庫有這條外鍵")

    real.close()
    fresh.close()
    return diffs


def cmd_schema() -> int:
    diffs = schema_diffs()
    if not diffs:
        print("兩邊 schema 完全一致——全新庫上的測試結論可以套用到正式環境。")
    else:
        print(f"差異 {len(diffs)} 項（每一項都是 pytest 看不到的死角）：")
        for d in diffs:
            print(f"  - {d}")
    return 1 if diffs else 0


def cmd_list() -> int:
    # 走品牌永久層的公開函式，不對它的資料表下原生 SQL（A1／鐵則 7，
    # app/tests/test_architecture_boundaries.py 會掃）。這支工具也不例外。
    copy, tmp = _open_copy()
    main = _boot(copy, tmp)
    from app.brand_intelligence import repository as repo  # noqa: E402
    conn = main.conn
    print("品牌：")
    for brand in repo.list_brands(conn):
        mark = "" if "虛構" in brand["name"] else "  <- 非虛構品牌，照全域規範不要拿它當測試對象"
        print(f"  {brand['status']:9} {brand['name']}{mark}")
        print(f"            {brand['id']}")
        for product in repo.list_products(conn, brand["id"]):
            print(f"              產品 {product['status']:9} {product['name']}  {product['id']}")
    return 0


def _leftovers(conn, column: str, value: str) -> dict:
    out = {}
    for t in _tables(conn):
        if column not in _cols(conn, t):
            continue
        n = conn.execute(f"SELECT COUNT(*) FROM {t} WHERE {column}=?", (value,)).fetchone()[0]
        if n:
            out[t] = n
    return out


def _brand_level_rows(conn, brand_id: str) -> dict:
    """真正的品牌層資料：product_id 為 NULL 的那些列。刪產品不該動到它們。

    不能直接數 brand_id——被刪產品自己的列也帶著 brand_id，數字當然會少，
    那不是誤刪。這個區別搞錯的話，真的誤刪品牌層資料時會被當成正常變化放過去。
    """
    out = {}
    for t in _tables(conn):
        cols = _cols(conn, t)
        if "brand_id" not in cols or "product_id" not in cols:
            continue
        n = conn.execute(
            f"SELECT COUNT(*) FROM {t} WHERE brand_id=? AND product_id IS NULL",
            (brand_id,)).fetchone()[0]
        if n:
            out[t] = n
    return out


def cmd_delete_brand(brand_id: str) -> int:
    copy, tmp = _open_copy()
    main = _boot(copy, tmp)
    from app.brand_intelligence import repository as repo  # noqa: E402
    conn = main.conn
    before = repo.get_brand(conn, brand_id)
    if before is None:
        sys.exit(f"找不到品牌：{brand_id}（先跑 list 看有哪些）")
    if "虛構" not in before["name"]:
        print(f"！ 「{before['name']}」不是虛構品牌。這只動複本不會傷到原檔，"
              f"但全域規範要求測試用虛構品牌，換一個比較好。")
    if before["status"] != "archived":
        repo.update_brand(conn, brand_id, name=before["name"],
                          client_name=before["client_name"], status="archived", actor="探針")
    print(f"目標：{before['name']}")
    print(f"刪除前有資料的表：{_leftovers(conn, 'brand_id', brand_id)}")
    repo.delete_brand(conn, brand_id, actor="探針")
    left = _leftovers(conn, "brand_id", brand_id)
    print(f"\n刪除成功。仍留著該品牌資料的表：{left if left else '無'}")
    print("預期只剩刻意保留的那幾張（見 app/tests/test_cleanup_coverage.py 的 DELIBERATELY_KEPT）")
    return 0


def cmd_delete_product(brand_id: str, product_id: str) -> int:
    copy, tmp = _open_copy()
    main = _boot(copy, tmp)
    from app.brand_intelligence import repository as repo  # noqa: E402
    conn = main.conn
    before = repo.get_product(conn, brand_id, product_id)
    if before is None:
        sys.exit(f"找不到產品：{product_id}（先跑 list 看有哪些）")
    brand_level_before = _brand_level_rows(conn, brand_id)
    if before["status"] != "archived":
        repo.update_product(conn, brand_id, product_id, name=before["name"],
                            status="archived", actor="探針")
    print(f"目標：{before['name']}")
    print(f"刪除前有資料的表：{_leftovers(conn, 'product_id', product_id)}")
    repo.delete_product(conn, brand_id, product_id, actor="探針")
    left = _leftovers(conn, "product_id", product_id)
    print(f"\n刪除成功。該產品仍留著資料的表：{left if left else '無（全清）'}")
    after = _brand_level_rows(conn, brand_id)
    changed = {t: (brand_level_before.get(t, 0), after.get(t, 0))
               for t in set(brand_level_before) | set(after)
               if brand_level_before.get(t, 0) != after.get(t, 0)}
    print(f"品牌層資料（product_id 為 NULL 的列，刪產品不該動到）："
          f"{'被動到了 -> ' + str(changed) if changed else '未受影響'}")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    cmd, rest = args[0], args[1:]
    if cmd == "schema":
        return cmd_schema()
    if cmd == "list":
        return cmd_list()
    if cmd == "delete-brand" and len(rest) == 1:
        return cmd_delete_brand(rest[0])
    if cmd == "delete-product" and len(rest) == 2:
        return cmd_delete_product(rest[0], rest[1])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
