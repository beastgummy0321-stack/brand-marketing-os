"""app/intake/state.py — 品牌建檔的草稿狀態（存 intake_draft 資料表，重啟可續接）。

每次讀寫都經 app/intake/repository.py 落地 DB。load 時把 photos_json／research_urls_json 轉回
畫面慣用的鍵名；花費（cost_spent / cost_items）不存副本，每次 load 都即時 SUM llm_task.cost
（03 §3A.5 第 5 點），供草稿花費上限 `would_exceed` 用。

F42-I14 拆掉舊階段（初掃印象、照片產品卡、AI 問答、交接包、貼回、賣什麼與數字）後，草稿 dict
只剩新七步還在用的欄位；舊欄位留在 schema（測試資料，本票不遷移），這裡不再讀寫。
"""

import os
import re

from app import storage
from app.core import input_rules
from app.core.db import new_id
from app.intake import repository as ir

# F42-I04: the seven brand-onboarding steps (prototype `#/b1`–`#/b7`). A draft without URLs
# and photos has nothing to scan and starts at step 3 (step 2 is skipped).
WIZARD_STEPS = [
    (1, "基本"),
    (2, "AI 讀網站"),
    (3, "品牌是誰"),
    (4, "證據與政策"),
    (5, "素材"),
    (6, "接工具"),
    (7, "完成"),
]


def _conn(conn=None):
    """沒帶連線就用 app.shared.web 的共用連線（延遲 import 避免循環匯入；修憲落地
    A4：原本讀 app.main，會跟 main.py 兜成循環，改讀 app.shared.web；連線在測試
    會被 reopen_connection() 換掉，所以每次都要即時取屬性）。"""
    if conn is not None:
        return conn
    import app.shared.web as main_mod
    return main_mod.conn


# ---------------------------------------------------------------------------
# DB 列 ↔ 畫面草稿 dict
# ---------------------------------------------------------------------------

def _loads(raw, default):
    """`raw` 是 jsonb 欄位讀出來的值：psycopg 已經解析成 dict/list，直接回傳即可
    （02-3b：不再是字串，不再需要 json.loads）。"""
    return raw if raw is not None else default


def _photos_to_db(photos: list) -> list:
    return [
        {"storage_key": p.get("storage_key"), "display_name": p.get("name"),
         "size_bytes": int(round((p.get("size_mb") or 0) * 1024 * 1024)),
         "token": p.get("token") or ""}
        for p in photos
    ]


def _row_to_draft(conn, row: dict) -> dict:
    brand_row = conn.execute("SELECT name FROM brand WHERE id = %s", (row["brand_id"],)).fetchone()
    photos = [
        {"name": p.get("display_name"), "storage_key": p.get("storage_key"),
         "size_mb": round((p.get("size_bytes") or 0) / (1024 * 1024), 1),
         "token": p.get("token") or ""}
        for p in _loads(row["photos_json"], [])
    ]
    draft = {
        "id": row["id"],
        "brand_id": row["brand_id"],
        "brand_name": brand_row["name"] if brand_row else "",
        "status": row["status"],
        "description": row["description"],
        "urls": _loads(row["research_urls_json"], []),
        "photos": photos,
        "budget_limit": float(row["cost_limit"]),
        "scan_done": row["scan_impressions_json"] is not None,
        "step": row["current_step"],
    }
    draft["cost_items"] = ir.list_llm_cost_items(conn, row)
    draft["cost_spent"] = sum(it["amount"] for it in draft["cost_items"] if not it["failed"])
    draft["resume_path"] = _resume_path(draft)
    return draft


def _resume_path(draft: dict) -> str:
    b = draft["brand_id"]
    return f"/app/brands/{b}/intake"


def save(draft: dict, conn=None) -> None:
    """把草稿 dict 的可變欄位寫回 intake_draft。`scan_done` 沿用舊欄位
    scan_impressions_json 非空當旗標（`skip_scan` 寫 []），不另開欄位。"""
    ir.update_draft(
        _conn(conn), draft["brand_id"], draft["id"],
        current_step=draft["step"],
        description=draft["description"],
        photos_json=_photos_to_db(draft["photos"]),
        research_urls_json=draft["urls"],
        scan_impressions_json=([] if draft["scan_done"] else None),
        cost_limit=draft["budget_limit"],
    )


def new_draft(brand_id: str, brand_name: str, *, description: str, urls: list, photos: list,
              actor: str = "", conn=None) -> dict:
    conn = _conn(conn)
    row = ir.create_draft(conn, brand_id, description, _photos_to_db(photos), urls, actor)
    return _row_to_draft(conn, row)


def get_draft(brand_id: str, conn=None) -> dict | None:
    conn = _conn(conn)
    row = ir.get_active_draft(conn, brand_id)
    return _row_to_draft(conn, row) if row else None


def invalid_url(urls: list) -> str | None:
    """回傳第一個格式不對的網址；全部合法回 None（S4.5）。"""
    return next((u for u in urls if not (u.startswith("http://") or u.startswith("https://"))), None)


def prev_photos(last_draft_row: dict | None) -> list:
    """上一輪草稿的照片（photos_json 形狀 → 畫面／new_draft 慣用形狀）；W1b 重新建檔沿用。"""
    if not last_draft_row:
        return []
    return [
        {"name": p.get("display_name"), "storage_key": p.get("storage_key"),
         "size_mb": round((p.get("size_bytes") or 0) / (1024 * 1024), 1),
         "token": p.get("token") or ""}
        for p in (last_draft_row["photos_json"] or [])
    ]


def skip_scan(draft: dict) -> None:
    """把掃描標成做完、不呼叫模型（『起始輸入沒東西可掃』）。"""
    draft["scan_done"] = True


def start_draft(conn, brand_id: str, brand_name: str, *, description: str, urls: list,
                photos: list, actor: str) -> dict:
    """草稿永遠建立（2026-09-14 起）。網址與照片皆空時（F42-I04），建完草稿後照 `skip_scan`
    把掃描標成做完、停在第 3 步；這條路徑上不准有任何模型呼叫。呼叫端（JSON API）先各自
    建好／取得品牌，這裡只管「建了草稿之後要不要略過掃描」這一刀。"""
    draft = new_draft(brand_id, brand_name, description=description, urls=urls, photos=photos,
                      actor=actor, conn=conn)
    # F42-I04: only URLs and photos are scanned (brand onboarding step 2); a description alone
    # no longer starts one.
    if not urls and not photos:
        skip_scan(draft)
        draft["step"] = 3
        save(draft, conn)
    return draft


def complete_draft(draft: dict, conn=None) -> None:
    ir.complete_draft(_conn(conn), draft["brand_id"], draft["id"])


def touch(draft: dict, path: str, step: int, conn=None) -> None:
    """記下「現在停在第幾步」，供續接連結使用。"""
    if draft["step"] != step:
        draft["step"] = step
        ir.update_draft(_conn(conn), draft["brand_id"], draft["id"], current_step=step)
    draft["resume_path"] = path


# ---------------------------------------------------------------------------
# 照片上傳（W1）：存進 Supabase Storage（app/storage，票 storage-03；ADR 0043 key 形狀
# `<org_id>/intake/<token>/<filename>`），本機磁碟不再落地。
#
# W1 送出時可能還沒有品牌（表單驗證失敗要重來），所以先用一個跟 brand_id 無關的暫存
# token 當 key 的一段；驗證通過真的建立品牌、寫進草稿後，token 這個暫存記錄就可以丟了。
# 暫存區留在記憶體沒關係——它只活在「表單還沒送成功」的幾分鐘內，不屬於草稿續接範圍。
# ---------------------------------------------------------------------------

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")

_PHOTO_CONTENT_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp",
}

# token -> [{"name":.., "size_mb":.., "storage_key":..}]（尚未落地成草稿前的暫存區）
PENDING_PHOTOS: dict = {}


def safe_filename(name: str) -> str:
    """os.path.basename 去掉路徑 + 危險字元換成 `_`，防路徑穿越（上傳檔名不可信任）。"""
    name = os.path.basename((name or "").strip())
    name = _UNSAFE_FILENAME_CHARS.sub("_", name)
    return name or "photo"


def new_photo_token() -> str:
    return new_id("pht")


def get_pending_photos(token: str) -> list:
    return list(PENDING_PHOTOS.get(token) or [])


def save_photo(token: str, filename: str, content: bytes, *, org_id: str) -> dict:
    """把這張照片的位元組存進 Storage（`<org_id>/intake/<token>/<filename>`），並記進
    token 的暫存清單。

    W1 驗證失敗、使用者補資料重送時，同一個 token 沿用已經存好的照片——不必也
    不會要求使用者重新選檔。
    """
    name = safe_filename(filename)
    key = f"{org_id}/intake/{token}/{name}"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    # F47 Contract A: the stored type is what the bytes are (a PNG named .jpg is stored as PNG).
    content_type = (input_rules.sniff(content)
                    or _PHOTO_CONTENT_TYPES.get(ext, "application/octet-stream"))
    storage.put(org_id=org_id, key=key, filename=name, content=content, content_type=content_type)
    entry = {"name": name, "size_mb": round(len(content) / (1024 * 1024), 1), "storage_key": key}
    PENDING_PHOTOS.setdefault(token, []).append(entry)
    return entry


def discard_pending_photos(token: str) -> None:
    """草稿建立後，照片已經轉存進 photos_json，暫存區這筆就不再需要——不刪 Storage 物件，
    草稿此刻已經引用它了（票 storage-03「Explicitly not fixed here」：中途放棄的精靈
    session 留下孤兒物件，跟今天留下孤兒檔案一樣，行為不變、範圍之外）。"""
    PENDING_PHOTOS.pop(token, None)


PHOTO_KINDS = ("image/jpeg", "image/png", "image/webp")


def validate_photo_upload(filename: str, content: bytes) -> str | None:
    """Brand photo check (S4.6): the content (not the extension) must be JPEG / PNG / WebP and
    not empty (F47 Contract A, `app.core.input_rules`), and one photo is at most 10 MB. Returns
    the user sentence, or None when it passes. The one check behind `/api/intake/photos`."""
    try:
        input_rules.check_image_upload(filename, content, PHOTO_KINDS)
    except input_rules.InputRuleError as exc:
        return str(exc)
    if round(len(content) / (1024 * 1024), 1) > 10:
        return f"「{filename}」超過 10 MB，請換一張小一點的照片。"
    return None


def save_new_photo(filename: str, content: bytes, *, org_id: str) -> dict:
    """新 API 專用：單檔上傳各自拿一個 token（跟舊表單「一批共用一個 token」語意不同，
    對應前端 `IntakePhoto{token,name,size_mb}`），底層仍是同一套 `save_photo` 存檔邏輯。"""
    token = new_photo_token()
    entry = save_photo(token, filename, content, org_id=org_id)
    return {"token": token, "name": entry["name"], "size_mb": entry["size_mb"]}


def resolve_photo_tokens(tokens: list) -> list:
    """把新 API 送來的 token 清單換成已上傳的照片；用完即從暫存區丟掉（草稿已經接手）。"""
    photos = []
    for token in tokens:
        pending = get_pending_photos(token)
        if pending:
            photos.append({**pending[0], "token": token})
        discard_pending_photos(token)
    return photos


# ---------------------------------------------------------------------------
# 花費（真實 token 成本：即時 SUM llm_task.cost，不存副本）
# ---------------------------------------------------------------------------

def would_exceed(draft: dict, amount: float) -> bool:
    """R3／W12：呼叫送出之前先判斷「已花費 + 本次預估 > 上限」。"""
    return draft["cost_spent"] + amount > draft["budget_limit"]


def require_draft(brand_id: str, conn=None) -> dict:
    """草稿不存在就丟 404（票 B3-intake：HTML／JSON 兩套路由共用同一個唯一入口）。"""
    draft = get_draft(brand_id, conn)
    if draft is None:
        import app.shared.web as main_mod
        raise main_mod.NotFoundKind("建檔進度")
    return draft


def require_draft_or_just_completed(brand_id: str, conn=None) -> dict:
    """The open draft, else the brand's latest completed one (`GET …/draft`: a finished brand
    re-entering the onboarding still reads its draft), else 404."""
    draft = get_draft(brand_id, conn)
    if draft is not None:
        return draft
    row = ir.get_latest_completed_draft(_conn(conn), brand_id)
    if row is not None:
        return _row_to_draft(_conn(conn), row)
    import app.shared.web as main_mod
    raise main_mod.NotFoundKind("建檔進度")
