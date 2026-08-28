"""app/shared/web.py — 全站共用的 web 工具（修憲落地 A4）。

從 app/main.py 拆出：原本 87 條品牌智庫業務路由跟 app/ads、app/orders、app/intake
一起頂著 app.main 的名字互相 import（含 main → ads.routes → main 的循環），
既違反 A1 三層地界的精神，也讓 app/main.py 永久豁免地界檢查這件事越滾越大——
第 3 條分支加入時，這個檔會膨脹到約 4000 行、150 條路由。

本檔放「每一條路由都會用到」的地基：DB 連線（conn，ADR 0027 起是 `coredb.ConnProxy()`，
每次呼叫即時轉發到這個 request／工作綁定的連線，見 app/core/db.py connection()）、
Jinja2 樣板、request context 組裝（ctx／banner_ctx）、品牌存取守門
（require_brand／require_product）、租戶界線（require_actor，票 03-1 起回傳
`app.identity.ActorContext` 而不是固定常數）、還有幾個純顯示用的小工具
（clean／parse_number／redirect_with_message／鮮度標示等）。

品牌永久層（app.brand_intelligence）在本檔的依賴方向是允許的——「品牌」是每條路由
都要碰的核心概念，這裡不算 A1 說的「分支專屬層」。真正要守住的是：本檔不得
import 任何分支專屬層（app.orders／app.intake 等），那些模組只能單向依賴這裡，
不能回頭 import app.main（app/ads/routes.py 等改成 `import app.shared.web as main_mod`
就是為了斷開這個回頭依賴，呼叫端寫法不變）。

票 03-1（ADR 0004 反轉為多租戶）：`require_actor()` 不再回傳固定常數，改回傳
`app.identity.ActorContext`（登入者的 user_id／org_id／role／email）。呼叫端寫法不變
（仍是 `actor = require_actor(request)`），但下游要具名字串（`audit_log.actor`、
`create_x(..., actor=...)` 等既有簽章）的地方要改傳 `str(actor.user_id)`。

`conn` 是 `ConnProxy()`，代理本身固定不換；它每次呼叫都即時查 `db.current()`（這個
request／工作綁定的那條連線），所以不需要、也沒有「重開一條換掉」這回事了。
"""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import JSONResponse as _FastAPIJSONResponse
from fastapi.responses import RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.brand_intelligence import repository as repo
from app.core import db as coredb
from app.core import vocab as md

BASE_DIR = Path(__file__).resolve().parent.parent  # .../app

conn = coredb.ConnProxy()


def to_json_value(value):
    """JSON 序列化邊界（02-3b）：DB 讀出的 datetime/date → ISO 字串，numeric(Decimal) → float。

    傳給 `json.dumps(..., default=to_json_value)`，只在遇到 json 原生不認得的型別時呼叫。
    """
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


class JSONResponse(_FastAPIJSONResponse):
    """比照 `fastapi.responses.JSONResponse`，多套一層 `to_json_value`（02-3b）。

    全站唯一的 JSON 序列化出口：直接回傳 dict 的路由已經靠 FastAPI 的
    `jsonable_encoder` 認得 datetime/Decimal，但顯式 `JSONResponse(...)` 繞過那層、
    直接 `json.dumps`——這裡補上同樣的轉換，讓呼叫端不用逐一路由手動轉字串。
    """

    def render(self, content) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            default=to_json_value,
        ).encode("utf-8")


# ---------------------------------------------------------------------------
# 資料存取的小包裝：補上「畫面需要、但 repository 沒有」的顯示邏輯
# ---------------------------------------------------------------------------

def _sorted_by_id(rows: list) -> list:
    """依 id 排序＝依建立時間排序（id 是可排序的 ULID 風格 id，見 core/db.py new_id）。

    repository 的清單查詢多半依 created_at／name 排序；品牌與產品清單這裡改回
    建立順序，貼近這個 UI 原本（Mock 資料）的呈現順序。
    """
    return sorted(rows, key=lambda r: r["id"])


def list_products(brand_id: str) -> list:
    return _sorted_by_id(repo.list_products(conn, brand_id))


def _color_index(brand_id: str, org_id: str) -> int:
    ids = sorted(b["id"] for b in repo.list_brands(conn, org_id))
    return ids.index(brand_id) % len(md.BRAND_COLOR_PALETTE)


def pending_brand_fact_count(brand_id: str) -> int:
    return len(repo.list_brand_facts(conn, brand_id, status="pending"))


def pending_product_layer_count(brand_id: str) -> int:
    """品牌底下所有產品的「待確認」筆數合計（產品事實＋產品經濟數字），功能選單提醒卡用。"""
    return repo.count_pending_product_layer(conn, brand_id)


def scope_label(brand_id: str, product_id: str | None) -> str:
    """畫面用語：適用範圍＝整個品牌 / 具體產品名稱（DESIGN.md §12.2）。"""
    if not product_id:
        return "整個品牌"
    product = repo.get_product(conn, brand_id, product_id)
    return product["name"] if product else "整個品牌"


def relative_time(value) -> str:
    """§12.1 規則 7：今天／昨天／N 天前／N 週前，超過 30 天改絕對日期。"""
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    days = (datetime.now(UTC) - dt).days
    if days <= 0:
        return "今天"
    if days == 1:
        return "昨天"
    if days < 7:
        return f"{days} 天前"
    if days < 30:
        return f"{days // 7} 週前"
    return dt.strftime("%Y-%m-%d")


FACT_STALE_DAYS = 180  # 事實鮮度門檻（天）：確認超過這麼久沒重新調研就提示過期，之後想調整只改這個數字


def fact_staleness(fact: dict) -> str | None:
    """confirmed 事實若確認時間超過 FACT_STALE_DAYS，回傳「上次確認 N 個月前」；
    pending 事實或未過門檻一律回傳 None（issue #5：純顯示，不動資料）。"""
    if fact.get("status") != "confirmed" or not fact.get("confirmed_at"):
        return None
    confirmed_at = fact["confirmed_at"]
    if not isinstance(confirmed_at, datetime):
        confirmed_at = datetime.fromisoformat(confirmed_at)
    if confirmed_at.tzinfo is None:
        confirmed_at = confirmed_at.replace(tzinfo=UTC)
    days = (datetime.now(UTC) - confirmed_at).days
    if days <= FACT_STALE_DAYS:
        return None
    return f"上次確認 {days // 30} 個月前"


REPORT_STALE_DAYS = 90  # 顧問報告鮮度門檻（天，決策 0017）：超過就提示重新生成，之後想調整只改這個數字


def report_staleness(report: dict) -> str | None:
    """report 超過 REPORT_STALE_DAYS 天沒重新生成時，回傳過期提示字串；未過門檻回 None。"""
    generated_at = report["generated_at"]
    if not isinstance(generated_at, datetime):
        generated_at = datetime.fromisoformat(generated_at)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=UTC)
    days = (datetime.now(UTC) - generated_at).days
    if days <= REPORT_STALE_DAYS:
        return None
    return f"這份報告已經是 {days} 天前生成的，市場與競爭觀察那一章可能過時了，建議重新生成。"


def _num_str(value) -> str:
    """數字轉字串塞回表單欄位：SQLite REAL 一律回傳 float，整數值要顯示成「1280」
    而不是「1280.0」（避免使用者看到跟自己輸入不一樣的字樣）。"""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _with_brand_names(rows: list) -> list:
    """打斷佇列項目掛上品牌名稱，供跨品牌頁面（首頁待辦、/inbox）顯示是哪個品牌的事。"""
    out = []
    for row in rows:
        brand = repo.get_brand(conn, row["brand_id"]) if row.get("brand_id") else None
        out.append({**row, "brand_name": brand["name"] if brand else None})
    return out


# 模型選單：id 是對 AI 服務的正式型號名（對外名稱，非內部代號），顯示名給人看。
# Claude Fable 5 定價查證見 app/llm/pricing.py 來源註記——比 Opus 5 貴約一倍，
# 只在需要最深推理與最長任務時才選（票 #27）。
MODEL_CHOICES = [
    ("claude-opus-5", "Claude Opus 5（預設，品質最好）"),
    ("claude-sonnet-5", "Claude Sonnet 5（速度與品質平衡）"),
    ("claude-haiku-4-5", "Claude Haiku 4.5（最便宜、最快）"),
    ("claude-fable-5", "Claude Fable 5（最強、最貴，價格約 Opus 5 的兩倍，適合最難的規劃與長任務）"),
]


# ---------------------------------------------------------------------------
# 共用小工具
# ---------------------------------------------------------------------------

class NotFoundKind(StarletteHTTPException):
    """404，帶著「找不到這個〔品牌／產品／…〕」要用的名詞。"""

    def __init__(self, kind: str):
        super().__init__(status_code=404, detail=kind)


class ApiError(Exception):
    """票 03-1 附錄 A：全站錯誤信封 `{"error": {"code","message","details"}}`。

    一個 FastAPI exception handler（app/main.py `handle_api_error`）統一把這個轉成 JSON。
    既有路由丟的 `HTTPException`／`NotFoundKind` 維持原樣不受影響（各自的 handler 沒變）——
    這是新路由（identity）專用的錯誤形狀，不強迫回填舊路由。
    """

    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


class Unauthenticated(ApiError):
    def __init__(self, message: str = "請先登入", details: dict | None = None):
        super().__init__(401, "unauthenticated", message, details)


class Forbidden(ApiError):
    def __init__(self, message: str = "沒有權限", code: str = "forbidden", details: dict | None = None):
        super().__init__(403, code, message, details)


class NotFound(ApiError):
    def __init__(self, message: str = "找不到", details: dict | None = None):
        super().__init__(404, "not_found", message, details)


def require_brand(brand_id: str, actor):
    """票 03-1：加上租戶界線——brand 存在但屬於別的組織一律視同不存在（404，不用 403，
    不洩漏「這個品牌其實存在，只是不是你的」這件事，見 03-plan.md D3-1 決策）。

    ponytail: 用「先按主鍵查出整列（含 org_id 欄），再用 Python 比對」而不是在 SQL 加
    `AND org_id = %s`——單筆主鍵查詢兩種寫法查詢成本相同，這裡不必為了「SQL 裡有沒有
    org_id 字樣」這件事再多過一次 repository 簽章改動；`require_brand` 本身就是全站
    唯一的品牌租戶界線關卡（217 個呼叫點都經過這裡），界線本身沒有變弱。
    """
    brand = repo.get_brand(conn, brand_id)
    if not brand or brand["org_id"] != actor.org_id:
        raise NotFoundKind("品牌")
    brand["color_index"] = _color_index(brand_id, actor.org_id)
    return brand


def require_product(brand, product_id: str):
    product = repo.get_product(conn, brand["id"], product_id)
    if not product:
        raise NotFoundKind("產品")
    return product


def require_actor(request: Request):
    """需要 actor 的路由一律呼叫這個，取得 `app.identity.ActorContext`（user_id/org_id/
    role/email）。票 03-1：取代 ADR 0004 那個固定操作人常數的作法——回到具名操作人，
    這次是「真的登入的人」而不是單機時代的假設。

    延遲 import：`app.identity` 依賴本檔（ApiError 系列、conn），模組層 import 會形成
    環；函式內延遲 import 是本庫既有的解環寫法（見 test_architecture_boundaries.py
    ImportCycleScanTest 檔頭說明、app/core/settings.py:108 同款前例）。
    """
    from app.identity import authenticate
    from app.shared import logging as app_logging

    actor = authenticate(request)
    app_logging.bind_actor(user_id=str(actor.user_id), org_id=actor.org_id)
    return actor


def banner_ctx(request: Request):
    """從 query string 讀出一次性提示條需要的欄位（PRG 轉址帶入）。"""
    qp = request.query_params
    return {
        "switched": qp.get("switched") == "1",
        "banner_kind": qp.get("kind"),
        "banner_msg": qp.get("msg"),
        "banner_again": qp.get("again"),
    }


def redirect_with_message(path: str, msg: str, kind: str = "ok",
                           anchor: str | None = None, again: str | None = None):
    params = {"kind": kind, "msg": msg}
    if again:
        params["again"] = again
    url = f"{path}?{urlencode(params)}"
    if anchor:
        url += f"#{anchor}"
    return RedirectResponse(url, status_code=303)


def parse_number(raw: str | None):
    """回傳 (value, ok)。空字串視為 None（選填欄位合法留空）。"""
    if raw is None or raw.strip() == "":
        return None, True
    try:
        return float(raw), True
    except ValueError:
        return None, False


def clean(raw: str | None) -> str:
    return (raw or "").strip()
