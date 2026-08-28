"""品牌層圖片風格偏好；以既有 app_setting 保存，無須新 schema。"""

from app.core import settings as core_settings

_KEY_PREFIX = "ads_style_preference:"


def _key(brand_id: str) -> str:
    return f"{_KEY_PREFIX}{brand_id}"


def get_text(conn, brand_id: str) -> str:
    """尚未設定的品牌沿用舊全域圖片批次開頭；明確空字串則代表不加片段。"""
    value = core_settings.get_setting(conn, _key(brand_id))
    if value is None:
        return core_settings.get_setting(conn, core_settings.IMAGE_PROMPT_HEADER_SETTING, "") or ""
    return value


def set_text(conn, brand_id: str, text: str) -> str:
    value = str(text or "").strip()
    core_settings.set_setting(conn, _key(brand_id), value)
    return value
