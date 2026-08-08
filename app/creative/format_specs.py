# -*- coding: utf-8 -*-
"""app/creative/format_specs.py — Meta 平台插槽的格式規格表（票 G1-A，2026-08-08 grill 定案）。

純資料，不寫類別、不寫 factory。目錄廣告刻意不進表（2026-08-08 定案：降級為排期建議）。

目標維度五個鍵（awareness/traffic/engagement/leads/sales）字面值複製自
app/ads/plan.py:50 的 OBJECTIVE_TEXT——本檔不 import app/ads（依賴方向鐵則：
app/creative 不得 import app/ads），一致性由 app/tests/test_format_specs.py
在測試裡 import app.ads.plan 比對。
"""

FORMAT_SPECS = {
    "single_image": {
        # 比例 4:5、1080×1350。來源查證日 2026-08-07。
        "ratio": "4:5",
        "pixels": (1080, 1350),
        "fields": {
            # 無字數預算；主題層互為替身：同訊息同圖上文字，只差配色/模特兒/角度。
            "image_prompt": {"count": 10, "char_budget": None},
            # Reels 版位約 40 字即截斷，不另設變體（G2 定案單圖只出 4:5）。
            "body": {"count": 5, "char_budget": 125},
            # Meta 顯示截斷約 27–40 依版位而異，取最嚴 27 當品質預算。
            "title": {"count": 5, "char_budget": 27},
            "description": {"count": 5, "char_budget": 30},
        },
        "objectives": {
            # sales：彈性格式，每主題媒體上限拉到 10。
            "sales": {"media_cap_per_theme": 10},
            # awareness/traffic/engagement/leads：媒體上限 1，文字仍 5 個走多文字最佳化。
            "awareness": {"media_cap_per_theme": 1},
            "traffic": {"media_cap_per_theme": 1},
            "engagement": {"media_cap_per_theme": 1},
            "leads": {"media_cap_per_theme": 1},
        },
        "sources": [
            {"url": "https://developers.facebook.com/docs/marketing-api/flexible-ad-format/", "checked_on": "2026-08-07"},
            {"url": "https://developers.facebook.com/documentation/ads-commerce/marketing-api/ad-creative/asset-feed-spec", "checked_on": "2026-08-07"},
            # 多文字最佳化不限購買目標。
            {"url": "https://www.facebook.com/business/help/2579898108796785", "checked_on": "2026-08-08"},
        ],
    },
    "carousel": {
        # 比例 1:1、1080×1080。
        "ratio": "1:1",
        "pixels": (1080, 1080),
        "card_count_min": 2,
        "card_count_max": 10,
        "narrative_types": {
            "steps": "步驟型：卡片數＝步驟數",
            "before_after": "對比型：固定 2 卡",
            "multi_product": "多商品型：卡片數＝商品數",
        },
        "fields": {
            "card_image_prompt": {"count": 1, "char_budget": None},
            "card_title": {"count": 1, "char_budget": 45},
            # 業界整理的顯示截斷值，Meta 官方規格未明列（查證日 2026-08-08）。
            "card_description": {"count": 1, "char_budget": 20},
            "body": {"count": 5, "char_budget": 80},  # 廣告層，非卡片層
        },
        "objectives": {
            # 五種目標皆可；每主題＝一套敘事＝一則廣告（媒體上限視為 1 套）。
            "awareness": {"media_cap_per_theme": 1},
            "traffic": {"media_cap_per_theme": 1},
            "engagement": {"media_cap_per_theme": 1},
            "leads": {"media_cap_per_theme": 1},
            "sales": {"media_cap_per_theme": 1},
        },
        # CTA 與連結不生成。多商品型每卡連結＝組裝時帶既有商品資料，屬 C 段組裝範圍，不是生成欄位。
        "sources": [
            {"url": "https://www.facebook.com/business/ads-guide/carousel", "checked_on": "2026-08-08"},
        ],
    },
    "video": {
        # 比例 9:16、1080×1920。
        "ratio": "9:16",
        "pixels": (1080, 1920),
        # 30 秒基準出自 app/methodology/creative-matrix.md 第 5 節「時間軸以 30 秒為基準，
        # 依實際長度等比縮放」；上限不硬性宣告，由所選框架決定。
        "duration_seconds_default": 30,
        "fields": {
            "script": {"count": 3, "char_budget": None},  # 每切角 3 支，至少跨 2 框架
            "hook_pool": {"count": 10, "char_budget": None},  # 每切角 10 個，跨腳本共用
            "body": {"count": 5, "char_budget": 125},
            "title": {"count": 5, "char_budget": 27},
            "description": {"count": 5, "char_budget": 30},
        },
        "objectives": {
            # 五種目標皆可；主題＝腳本。
            "awareness": {"media_cap_per_theme": 1},
            "traffic": {"media_cap_per_theme": 1},
            "engagement": {"media_cap_per_theme": 1},
            "leads": {"media_cap_per_theme": 1},
            "sales": {"media_cap_per_theme": 1},
        },
        "sources": [
            {"url": "https://www.facebook.com/business/ads-guide/video", "checked_on": "2026-08-08"},
        ],
    },
}
