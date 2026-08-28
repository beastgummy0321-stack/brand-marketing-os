"""app/ads/creative_matrix.py — 創意矩陣接線用的封閉枚舉（票 7，決策 0023 第 10、11 點）。

app/methodology/creative-matrix.md 是角度與規則的權威內容——完整表格已經透過
app/llm/methodology.py 整份塞進生成 prompt（見 app/ads/creative.py 的
METHODOLOGY_TASK_LABELS）。這裡不重抄一次 35 個角度的說明文字，只放「驗形要用的
封閉枚舉」：角度編號的合法範圍、Hook 切法的封閉詞彙。改文件內容不用改這裡；
只有新增／刪除角度編號範圍或切法種類才要動這個檔案。

切法用封閉枚舉（不是自由文字）是因為「橫跨多種切法」要能程式判定——放給模型自己
造詞，同一種切法換句話說也能造出不同字串，擋不住 issue 點名的「同義改寫充數」。
"""

ANGLE_NUMBER_MIN = 1
ANGLE_NUMBER_MAX = 35  # 對應 creative-matrix.md 第一節「35 個創意角度」的編號範圍

# Hook 切法（creative-matrix.md 第四節，共 11 種）。
CUT_TYPES = {
    "pain_visualized": "痛點具象化",
    "counterintuitive": "反直覺宣稱",
    "identity_callout": "身分點名",
    "precise_dissuasion": "精準勸退",
    "contrast_pairing": "對比夾擊",
    "value_reframe": "價值反轉",
    "suspense_countdown": "懸念倒數",
    "self_deprecating": "自黑打臉",
    "scene_intrusion": "場景闖入",
    "number_impact": "數字衝擊",
    "sound_first": "聲音前置強化",
}

HOOK_CUT_TYPE_MIN_DISTINCT = 3
# ponytail: 固定門檻 3，沒有跟著每批 Hook 數量等比例調整（方法論原文講的是「10 組
# 至少橫跨 5 種」，這裡單批通常遠小於 10 組）。之後若素材批量拉到 10 組以上，
# 門檻要跟著調高，不能一直用 3。


def is_valid_angle_number(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) \
        and ANGLE_NUMBER_MIN <= value <= ANGLE_NUMBER_MAX


def cut_type_vocabulary() -> str:
    """給模型看的切法枚舉清單——模型只能從這些 key 裡挑，不能自己發明切法。"""
    return "、".join(f"{key}（{label}）" for key, label in CUT_TYPES.items())


def hook_diversity_ok(cut_types: list) -> bool:
    """這批 Hook 各自的切法 key 是否夠多樣。切法數不足視為同義改寫充數，驗形擋下。

    只有 1 則（或沒有）Hook 時沒得比較，不算違規；到門檻前用「這批 Hook 數量」
    當上限，避免小批量永遠過不了關。
    """
    if len(cut_types) < 2:
        return True
    required = min(HOOK_CUT_TYPE_MIN_DISTINCT, len(cut_types))
    return len(set(cut_types)) >= required
