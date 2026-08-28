"""品牌層圖片風格偏好；以既有 app_setting 保存，無須新 schema。"""

from app.brand_intelligence import repository as bi_repo
from app.core import settings as core_settings

_KEY_PREFIX = "ads_style_preference:"


def _key(brand_id: str) -> str:
    return f"{_KEY_PREFIX}{brand_id}"


def get_text(conn, brand_id: str) -> str:
    """尚未設定的品牌沿用舊全域圖片批次開頭；明確空字串則代表不加片段。"""
    org_id = bi_repo._org_id_for_brand(conn, brand_id)
    value = core_settings.get_setting(conn, _key(brand_id), org_id=org_id)
    if value is None:
        return core_settings.get_setting(
            conn, core_settings.IMAGE_PROMPT_HEADER_SETTING, "", org_id=org_id) or ""
    return value


def set_text(conn, brand_id: str, text: str) -> str:
    value = str(text or "").strip()
    brand = bi_repo.get_brand(conn, brand_id)
    assert brand is not None, f"找不到品牌：{brand_id}"
    core_settings.set_setting(conn, _key(brand_id), value, org_id=brand["org_id"])
    return value
