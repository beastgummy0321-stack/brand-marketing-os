"""python -m app.intake.card_test — 操作卡實測工具。

做什麼：把「Claude 操作卡」會請使用者複製的那段交接包文字，經真實 API 送給
設定頁選定的模型，然後驗證回覆的總結表能不能被 app/intake/paste_parse.py 讀進來，
以人話輸出結果。用途：在真的請客戶操作之前，先確認交接包的輸出契約跟模型談得攏。

- 沒有金鑰時：印出人話提示後直接結束（exit code 0），不發任何網路請求。
- ChatGPT 操作卡無法用本工具自動測（我們沒有 OpenAI 介接）：請使用者手動開
  ChatGPT、照 W7 操作卡步驟貼上同一段文字、把結果貼回 W8 驗證。
- 本工具走 provider 直呼，不寫 llm_task（沒有品牌、沒有草稿，記帳沒有掛的地方）。
"""

import sys

from app.core import settings as coresettings
from app.intake import paste_parse, script
from app.llm import providers


def _sample_draft() -> dict:
    """組一份示範草稿（§14.3 品牌 C 的內容），給 build_prompt 用。"""
    return {
        "brand_name": "小滿製茶（操作卡實測）",
        "description": "做台灣中南部小農的烏龍與紅茶，主打單一產區、冷泡也不苦。",
        "scan_impressions": list(script.SCAN_IMPRESSIONS),
        "answers": [
            {"question": script.QUESTIONS[0]["question"],
             "choice_label": script.QUESTIONS[0]["suggested"]["label"], "note": ""},
            {"question": script.QUESTIONS[1]["question"],
             "choice_label": script.QUESTIONS[1]["suggested"]["label"], "note": ""},
        ],
    }


def main() -> int:
    if not coresettings.get_api_key():
        print("還沒有設定 AI 金鑰，這次不送出任何請求。")
        print("請先到系統的「設定」頁填入金鑰，之後再執行一次：python -m app.intake.card_test")
        print("（ChatGPT 操作卡無法自動測：請手動開 ChatGPT 照 W7 步驟貼上交接包文字，"
              "再把結果貼回 W8 驗證。）")
        return 0

    prompt = script.build_prompt(_sample_draft(), "standard",
                                 known_products=[script.MOCK_PRODUCT_NAME])
    model = coresettings.get_llm_model()
    print(f"用模型「{model}」送出 Claude 操作卡的交接包文字（標準調研），等它回覆⋯⋯")
    provider = providers.AnthropicProvider()
    try:
        resp = provider.complete(model=model, system=None,
                                  messages=[{"role": "user", "content": prompt}],
                                  max_tokens=16000, timeout_s=300.0)
    except providers.ProviderError as exc:
        print(f"這次呼叫沒有成功：{exc}")
        return 1

    rows, errors = paste_parse.parse_paste(resp.output_text, {script.MOCK_PRODUCT_NAME},
                                           brand_name=_sample_draft()["brand_name"])
    print(f"回覆共 {len(resp.output_text)} 字。")
    if rows is not None:
        print(f"結果：總結表讀得進來，共 {len(rows)} 列，格式驗證全部通過。")
        return 0
    print(f"結果：總結表讀不進來，共 {len(errors)} 個問題：")
    for e in errors[:10]:
        print(f"  - {e['msg']}")
    print("建議：檢視 script.output_contract_block() 的措辭，或把上面的錯誤拿去調整輸出契約。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
