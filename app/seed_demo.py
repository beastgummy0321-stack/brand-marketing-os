# -*- coding: utf-8 -*-
"""app/seed_demo.py — 把示範資料（內容定義見 app/mock_data.DEMO_BRANDS）寫入 DB。

用法：
    python -m app.seed_demo            # DB 已有品牌就拒絕執行，避免誤蓋掉真實資料
    python -m app.seed_demo --force    # 清空 brand_intelligence 全部資料表後重建

不動 app/core/db.py 的預設 DB 路徑；要種到別的 DB 檔，設定環境變數 BRAND_OS_DB。
"""

import argparse
import sys
from datetime import datetime, timezone

from app import mock_data as demo
from app.brand_intelligence import repository as repo
from app.core import db
from app.intake import state as intake_state

SEED_ACTOR = "示範資料匯入"

# brand_intelligence 12 張表，依外鍵相依順序排列，--force 清空重建時照這個順序刪
_TABLES_FK_ORDER = [
    "intake_item", "intake_draft", "llm_task",
    "brand_fact", "product_fact", "product_economics", "brand_performance_baseline",
    "rule", "claim", "official_asset", "strategy_hypothesis", "owned_channel",
    "source_reference", "product", "brand",
]


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _create_source(conn, brand_id: str, text) -> str:
    text = (text or "").strip()
    if not text:
        return None
    row = repo.create_source_reference(
        conn, brand_id, actor=SEED_ACTOR, title=text, source_type="other", captured_date=_today(),
    )
    return row["id"]


def _create_fact(conn, brand_id: str, product_id, f: dict) -> None:
    src_id = _create_source(conn, brand_id, f.get("source_reference"))
    kwargs = dict(
        actor=SEED_ACTOR, fact_type=f["fact_type"], label=f["label"], value=f["value"],
        status=f["status"], source_reference_id=src_id, confirmed_by=f.get("confirmed_by"),
    )
    if product_id:
        repo.create_product_fact(conn, brand_id, product_id, **kwargs)
    else:
        repo.create_brand_fact(conn, brand_id, **kwargs)


def _seed_brand(conn, b: dict) -> None:
    brand = repo.create_brand(conn, name=b["name"], client_name=b.get("client_name"), actor=SEED_ACTOR)
    brand_id = brand["id"]

    for f in b.get("brand_facts", []):
        _create_fact(conn, brand_id, None, f)

    product_ids = {}
    for p in b.get("products", []):
        product = repo.create_product(conn, brand_id, name=p["name"], actor=SEED_ACTOR)
        product_ids[p["ref"]] = product["id"]
        for f in p.get("facts", []):
            _create_fact(conn, brand_id, product["id"], f)
        econ = p.get("economics")
        if econ:
            repo.save_product_economics(conn, brand_id, product["id"], actor=SEED_ACTOR, **econ)

    for r in b.get("rules", []):
        product_id = product_ids.get(r["product_ref"]) if r.get("product_ref") else None
        src_id = _create_source(conn, brand_id, r.get("source_reference"))
        repo.create_rule(
            conn, brand_id, actor=SEED_ACTOR, rule_type=r["rule_type"], content=r["content"],
            severity=r["severity"], product_id=product_id, source_reference_id=src_id,
        )

    for c in b.get("claims", []):
        product_id = product_ids.get(c["product_ref"]) if c.get("product_ref") else None
        src_id = _create_source(conn, brand_id, c.get("evidence_source_reference"))
        repo.create_claim(
            conn, brand_id, actor=SEED_ACTOR, claim_text=c["claim_text"], claim_type=c["claim_type"],
            product_id=product_id, evidence_source_reference_id=src_id,
        )

    for ch in b.get("channels", []):
        repo.create_channel(
            conn, brand_id, actor=SEED_ACTOR, channel_type=ch["channel_type"], name=ch["name"],
            identifier=ch.get("identifier"), status=ch.get("status", "active"),
        )

    if b.get("seed_intake_draft"):
        intake_state.seed_in_progress_draft(brand_id, brand["name"], conn=conn)


def _wipe(conn) -> None:
    for table in _TABLES_FK_ORDER:
        conn.execute(f"DELETE FROM {table}")
    conn.execute("DELETE FROM audit_log")
    conn.commit()


def seed(conn, force: bool = False) -> bool:
    """回傳 True 表示真的寫入了；False 表示因為 DB 已有品牌而拒絕（未加 --force）。"""
    existing = repo.list_brands(conn)
    if existing:
        if not force:
            print(f"DB 已有 {len(existing)} 個品牌，拒絕執行以免覆蓋既有資料。"
                  "若確定要清空重建，請加上 --force。")
            return False
        _wipe(conn)

    for brand_def in demo.DEMO_BRANDS:
        _seed_brand(conn, brand_def)
    print(f"已寫入 {len(demo.DEMO_BRANDS)} 個示範品牌。")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="把示範資料寫入 DB")
    parser.add_argument("--force", action="store_true", help="DB 已有品牌時，清空重建")
    args = parser.parse_args()

    conn = db.connect_and_migrate()
    try:
        ok = seed(conn, force=args.force)
    finally:
        conn.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
