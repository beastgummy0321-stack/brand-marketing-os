"""app/storage/__init__.py — single entry point (container contract §1, ticket storage-01).

集裝箱憲章 §1 邊界定案：
1. 對外進入點：本檔（`app/storage/__init__.py`）。這是全站唯一知道 Supabase Storage 存在的
   地方——沒有其他模組建 Storage URL、讀 `SUPABASE_SERVICE_ROLE_KEY`、或看得到 httpx 物件。
2. 進出形狀：
       put(*, org_id, key, filename, content, content_type) -> str   # 回傳存進去的 key
       get(*, org_id, key) -> tuple[bytes, str]                      # (bytes, content_type)
       delete(*, org_id, key) -> None
       delete_prefix(*, org_id, prefix) -> None
   四個以外不對外。錯誤形狀：`NotFound`（get() 對到不存在的 key）、`StorageError`（其餘所有
   失敗——Storage 不可達、非預期狀態碼／body，見下方「錯誤模型」）；`ValueError`（key／prefix
   第一段不是傳入的 org_id——租戶邊界檢查，見下方）。
3. 呼叫端：目前沒有——票 02、03 是它的第一批呼叫端（app/brand_web、app/intake）。本模組自己
   的測試檔是唯一呼叫端。
4. 不碰什麼：不 import 任何租戶模組（`app.brand_intelligence`／`app.intake`／`app.brand_web`
   等）；本模組是基礎設施，比照 `app.background`（ADR 0038 的先例），只依賴 stdlib／httpx／
   環境變數。不對外暴露 httpx 物件、不暴露 Storage 回應的原始 JSON。

租戶邊界（SPEC D4）：四個函式都先檢查 key／prefix 的第一段是不是呼叫者傳入的 org_id，檢查
在任何 HTTP 呼叫之前做，失敗丟 `ValueError`。這就是隔離檢查本身，不是防禦性寫法。

錯誤模型（SPEC D3/D9，2026-08-30 對本機 Storage 探測過，不是猜的）：物件不存在跟重複上傳都是
HTTP 400，真正的狀態藏在 body 的 `code` 欄位（`NoSuchKey` / `KeyAlreadyExists`），HTTP status
本身不能拿來判斷——`if resp.status_code == 404` 是死碼。Storage 不是 best-effort：金鑰缺漏、
Storage 打不通、任何非預期的 body，一律往外丟，沒有「回報成功但其實什麼都沒存」這種結果。

`delete_prefix` 的做法（SPEC D3，同樣探測過，不是猜的）：`DELETE .../object/<bucket>` 帶
`{"prefixes":[...]}` 只匹配「完整物件名稱」，給它一個前綴會回 `200 []` 但什麼都沒刪——是靜默
的資料遺失，不是捷徑。正確做法是 `POST .../object/list-v2/<bucket>` 遞迴列出完整 key、蒐集
之後才用 `DELETE`+`prefixes` 刪那些完整 key，`hasNext` 為真就重複列。`POST .../object/list/
<bucket>` 不遞迴，回傳的是虛擬資料夾層，這裡不用。
"""

import os

import httpx

_BUCKET = "assets"


class StorageError(Exception):
    """app.storage 呼叫失敗——沒有 best-effort，失敗一律往外丟（SPEC D9）。"""


class NotFound(StorageError):
    """`get()` 對到不存在的 key。"""


def _base_url() -> str:
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not base:
        raise StorageError("SUPABASE_URL 未設定，無法呼叫 Storage")
    return base


def _headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not key:
        raise StorageError("SUPABASE_SERVICE_ROLE_KEY 未設定，無法呼叫 Storage")
    return {"Authorization": f"Bearer {key}"}


def _guard_tenant(org_id: str, key_or_prefix: str, *, label: str) -> None:
    first_segment = key_or_prefix.split("/", 1)[0]
    if first_segment != org_id:
        raise ValueError(f"{label} 第一段必須是 org_id（{org_id!r}），實際是 {key_or_prefix!r}")


def _error_code(resp: httpx.Response) -> str | None:
    try:
        return resp.json().get("code")
    except ValueError:
        return None


def put(*, org_id: str, key: str, filename: str, content: bytes, content_type: str) -> str:
    """上傳（覆蓋既有同名物件，`x-upsert: true`）。回傳存進去的 key。"""
    _guard_tenant(org_id, key, label="key")
    resp = httpx.post(
        f"{_base_url()}/storage/v1/object/{_BUCKET}/{key}",
        headers={**_headers(), "Content-Type": content_type, "x-upsert": "true"},
        content=content,
        timeout=30.0,
    )
    if resp.status_code >= 400:
        raise StorageError(f"上傳失敗（{filename}）：{resp.status_code} {resp.text}")
    return key


def get(*, org_id: str, key: str) -> tuple[bytes, str]:
    """下載。回傳 (bytes, content_type)。對到不存在的 key 丟 `NotFound`。"""
    _guard_tenant(org_id, key, label="key")
    resp = httpx.get(
        f"{_base_url()}/storage/v1/object/{_BUCKET}/{key}", headers=_headers(), timeout=30.0
    )
    if resp.status_code >= 400:
        if _error_code(resp) == "NoSuchKey":
            raise NotFound(f"物件不存在：{key}")
        raise StorageError(f"下載失敗（{key}）：{resp.status_code} {resp.text}")
    content_type = resp.headers.get("content-type", "application/octet-stream")
    return resp.content, content_type


def delete(*, org_id: str, key: str) -> None:
    """刪除單一物件。物件本來就不存在也視為成功（冪等）。"""
    _guard_tenant(org_id, key, label="key")
    resp = httpx.request(
        "DELETE",
        f"{_base_url()}/storage/v1/object/{_BUCKET}",
        headers={**_headers(), "Content-Type": "application/json"},
        json={"prefixes": [key]},
        timeout=30.0,
    )
    if resp.status_code >= 400:
        raise StorageError(f"刪除失敗（{key}）：{resp.status_code} {resp.text}")


def _list_v2(prefix: str) -> list[str]:
    """遞迴列出 `prefix` 底下所有物件的完整 key（`hasNext` 為真就重複列）。

    分頁靠 `cursor`，不是「同一個 body 再打一次」——探測過（2026-08-30，105 個物件、
    `limit: 10`）：第二頁不帶上一頁回傳的 `nextCursor`，API 會原地回同一頁，不會往前走。
    """
    keys: list[str] = []
    cursor: str | None = None
    while True:
        payload: dict = {"prefix": prefix}
        if cursor:
            payload["cursor"] = cursor
        resp = httpx.post(
            f"{_base_url()}/storage/v1/object/list-v2/{_BUCKET}",
            headers={**_headers(), "Content-Type": "application/json"},
            json=payload,
            timeout=30.0,
        )
        if resp.status_code >= 400:
            raise StorageError(f"列出物件失敗（{prefix}）：{resp.status_code} {resp.text}")
        body = resp.json()
        keys.extend(obj["name"] for obj in body.get("objects", []))
        if not body.get("hasNext"):
            return keys
        cursor = body.get("nextCursor")


def delete_prefix(*, org_id: str, prefix: str) -> None:
    """刪除 `prefix` 底下所有物件：list-v2 蒐集完整 key → 用那些完整 key 呼叫 DELETE。

    `DELETE`+`prefixes` 只匹配完整物件名稱，不能拿前綴直接餵它（見模組檔頭）。
    """
    _guard_tenant(org_id, prefix, label="prefix")
    keys = _list_v2(prefix)
    if not keys:
        return
    resp = httpx.request(
        "DELETE",
        f"{_base_url()}/storage/v1/object/{_BUCKET}",
        headers={**_headers(), "Content-Type": "application/json"},
        json={"prefixes": keys},
        timeout=30.0,
    )
    if resp.status_code >= 400:
        raise StorageError(f"刪除前綴失敗（{prefix}）：{resp.status_code} {resp.text}")
