# -*- coding: utf-8 -*-
"""app/brand_intelligence/repository_learning_text.py — 學習文字去重正規化。

從 `repository.py` 拆出（票 F3-signoff-residue R4）：修多括號區段全部刪空互撞的缺陷
需要多加一段 fallback 邏輯，`repository.py` 行數已頂到 `docs/tech-debt.md` 凍結的行數
上限，加不進去，得先拆（CLAUDE.md 第五節；precedent：`repository_channels.py`）。
`repository.py` 保留一行 re-export（`from app.brand_intelligence.repository_learning_text
import _normalize_learning_text`），既有呼叫端與測試的 `bi_repo._normalize_learning_text(...)`
寫法不必改。

R5（orchestrator ruling，票 F3-signoff-residue）：R3/R4 把「」『』【】和括號一起當成
「補充夾註」整段刪空，三次覆核都被打回——中文的「」『』是引號，框住的是結論本身
（「…比…高」vs「…比…低」），不是可以丟掉的舉例性資訊，刪空等於把兩個相反結論的句子
洗成同一句。改成兩家族分開處理：括號家族（（）、()、〔〕）維持「刪空夾註」，引號／標籤
家族（「」『』【】）只統一分隔符寫法、內容全部保留繼續參與比對。

對外進入點：`_normalize_learning_text()`（誰依賴它：`repository.py` 的
`learning_ledger_entry_exists()` re-export；`app/tests/test_ads_reading_hypotheses.py`
直接測正規化函式本身）。
"""

import re

# 括號家族：全形／半形小括號、龜殼括號——內容是舉例性補充夾註，去重時整段丟棄（B0-23 原案）。
_LEARNING_ASIDE_RE = re.compile(r"[（(][^）)]*[）)]|〔[^〕]*〕")
# 引號／標籤家族：直角引號、雙直角引號、方頭括號——框住的是結論本身，絕對不能刪空，
# 只把三種分隔符統一成同一種寫法（這裡選「」），換了引號寫法的兩句話才對得上，
# 內容原封不動留著繼續參與比對。
_LEARNING_QUOTE_RE = re.compile(r"「([^「」]*)」|『([^『』]*)』|【([^【】]*)】")
# 拿掉夾註後常留下孤兒標點（黏在一起或句尾懸空）：連續 2 個以上收斂成 1 個、頭尾整段砍掉。
_STRAY_PUNCT_RE = re.compile(r"[，,、；;：:。.]{2,}")
_EDGE_PUNCT_RE = re.compile(r"^[，,、；;：:。.]+|[，,、；;：:。.]+$")


def _canon_quote_delimiters(text: str) -> str:
    """引號家族分隔符統一成「」，內容一個字都不丟——`_LEARNING_ASIDE_RE` 才是唯一會刪
    夾註內容的規則，這裡只換符號。"""
    def _replace(m: "re.Match[str]") -> str:
        inner = next(g for g in m.groups() if g is not None)
        return "「" + inner + "」"
    return _LEARNING_QUOTE_RE.sub(_replace, text)


def _clean_learning_text(s: str) -> str:
    """收斂內部空白、收斂孤兒標點、去頭尾標點——三個候選字串共用的最後一道清理。"""
    s = re.sub(r"\s+", "", s)
    s = _STRAY_PUNCT_RE.sub("，", s)
    return _EDGE_PUNCT_RE.sub("", s).strip()


def _normalize_learning_text(text: str) -> str:
    """去重比對前先統一引號分隔符（內容保留，見 `_canon_quote_delimiters`），再拿掉括號
    家族的補充夾註（家族見 `_LEARNING_ASIDE_RE`）、收斂內部空白、清孤兒標點——LLM 措辭
    常只差在舉例性夾註或排版空白，逐字全等會誤判成新學習（R2-learning-honesty 契約第 5
    點：B0-23）。依序試三個候選、第一個清完非空的就用（票 F3 R4：sign-off residue 覆核）
    ——R3 版整段刪除夾註時，兩個以上括號區段每一段各自只看「這一段以外還剩什麼」，看到的
    都是別段還在、於是每段都判自己該刪，全部段落刪光變成空字串，結論相反的兩句話一起洗成
    空字串誤判重複。改成先試「整段刪夾註」，刪完空的話退回「拆括號留內容」，兩個都還是空
    的話（極端全空白／純標點輸入）退回原文——保證非空輸入永遠不會被正規化成空字串。"""
    canon = _canon_quote_delimiters(text)
    for candidate in (
        _LEARNING_ASIDE_RE.sub("", canon),
        _LEARNING_ASIDE_RE.sub(lambda m: m.group(0)[1:-1], canon),
        canon,
    ):
        cleaned = _clean_learning_text(candidate)
        if cleaned:
            return cleaned
    return text
