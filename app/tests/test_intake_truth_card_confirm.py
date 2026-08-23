"""Truth-card confirm guards (split from test_intake_t2_backend.py at the 800-line cap)."""
from fastapi.testclient import TestClient

import app.main as main
from app.brand_intelligence import repository as bi_repo
from app.intake import repository as ir
from app.intake import state

ACTOR = "測試員"


def test_truth_card_batch_rejects_product_fact_scoped_to_whole_brand_before_writing_anything():
    """e2e-adflow 修復驗證：交接包在品牌沒產品時叫外部 AI 只填「整個品牌」，貼回的
    「產品事實｜…｜整個品牌」列走到真相卡確認會在 _ensure_product 炸 ValueError → 500。
    要在任何一列落檔前就擋成 400，並指名哪幾條要按「改」掛到真正的產品。"""
    brand = bi_repo.create_brand(main.conn, name="虛構無產品品牌", client_name=None, actor=ACTOR)
    draft = state.new_draft(brand["id"], brand["name"], description="沒有產品就建檔。",
                            urls=[], photos=[], actor=ACTOR, conn=main.conn)
    items = ir.create_items(main.conn, brand["id"], draft["id"], [
        {"kind": "品牌事實", "category": "定位", "title": "產地直送",
         "content": "只使用虛構果園原料。", "scope": "整個品牌", "evidence": "測試資料"},
        {"kind": "產品事實", "category": "價格帶", "title": "產品售價",
         "content": "售價等使用者補。", "scope": "整個品牌", "evidence": "測試資料"},
        {"kind": "宣稱", "category": "高風險", "title": "幫助消化",
         "content": "需要決定可不可以講。", "scope": "整個品牌", "evidence": "測試資料"},
        {"kind": "產品事實", "category": "核心資訊", "title": "單包規格",
         "content": "一包十顆。", "scope": "整個品牌", "evidence": "測試資料"},
    ])
    extra = items[3]

    response = TestClient(main.app).post(
        f"/api/intake/brands/{brand['id']}/truth-card/confirm",
        json={"answers": {
            items[1]["id"]: {"value": "NT$ 480"},
            items[2]["id"]: {"decision": "cannot_say"},
        }},
    )

    assert response.status_code == 400, response.text
    assert "單包規格" in response.json()["error"] and "產品售價" in response.json()["error"]
    pending_ids = {item["id"] for item in ir.list_pending_items(main.conn, brand["id"], draft["id"])}
    assert pending_ids == {items[0]["id"], items[1]["id"], items[2]["id"], extra["id"]}
