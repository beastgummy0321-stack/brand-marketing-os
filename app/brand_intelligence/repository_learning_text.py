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
直接測正規化函式本身）、`collapse_learnings()`（誰依賴它：`app/ads/routes_learnings_api.py`
累積智慧頁、`app/ads/cockpit_extras.py` 駕駛艙計數、
`app/ads/routes_campaigns_performance_api.py` 覆盤頁、`app/llm/context_compiler.py`
企劃 prompt——四個讀取面全部收斂同一組規則，見 ADR 0026）。
"""

import re
from datetime import datetime, timezone

_MIN_TS = datetime.min.replace(tzinfo=timezone.utc)  # learned_at 排序用的最小值墊底（02-3b：型別改 datetime 後 "" 不再能跟它比大小）

# 括號家族：全形／半形小括號、龜殼括號——內容是舉例性補充夾註，去重時整段丟棄（B0-23 原案）。
# content class 額外排除引號分隔符「」（票 F3 R6 orchestrator ruling）：原本只排除自家的
# 收尾符號，遇到「括號裡面包一段引號」（例如（「高」）／〔『低』〕）會貪婪吃穿引號、跨到
# 右括號整段刪空，把引號框住的結論本身一起洗掉，兩個相反結論的句子就撞成同一句（false
# positive：誤判成重複，靜靜吞掉一筆真的新學習）。排除引號分隔符後，這種巢狀夾註不再被
# 這條規則配對到，代價是這種夾註不再被刪空、近似重複可能漏抓（false negative：多記一筆、
# 使用者看得到也改得掉）。ruling 選了後者：漏抓比誤刪安全，兩者不能都要。
_LEARNING_ASIDE_RE = re.compile(r"[（(][^）)「」]*[）)]|〔[^〕「」]*〕")
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


def collapse_learnings(rows: list) -> list:
    """同一條學習只留一列（ADR 0026 決定 1、4、5）。

    分組鍵＝(正規化後的 learning_text, product_id)——決定 1 的兩項判準，一項不多一項不少
    （同句話掛不同 product_id 不合併，各自是自己範圍內的結論）。每組代表列＝原始
    learning_text 最長的那一列（決定 5：切角名字住在括號夾註裡，最長那列保留最多名字），
    長度相同時取 learned_at 最新的——`max()` 對相同鍵值取第一個遇到的最大值，只要輸入順序
    固定，結果就是決定性的，不需要額外的第二層 tie-break。

    代表列補三個新 key、其餘欄位原封不動沿用代表列：
    - verified_cycles：這組有幾列（＝被幾期各自驗證過）
    - sample_sizes：這組各列的 sample_size，learned_at 由舊到新，None 跳過不填佔位
    - member_ids：這組所有列的 id（learned_at 由舊到新，可追溯「這條是哪幾筆合起來的」）

    輸出順序＝輸入順序（以每組代表列在輸入中的位置為準）。純函式，不吃 conn。
    """
    groups: "dict[tuple, list[tuple[int, dict]]]" = {}
    for idx, row in enumerate(rows):
        key = (_normalize_learning_text(row["learning_text"]), row["product_id"])
        groups.setdefault(key, []).append((idx, row))

    collapsed = []
    for group in groups.values():
        rep_idx, representative = max(
            group, key=lambda pair: (len(pair[1]["learning_text"]), pair[1].get("learned_at") or _MIN_TS)
        )
        members = sorted(group, key=lambda pair: pair[1].get("learned_at") or _MIN_TS)
        merged = dict(representative)
        merged["verified_cycles"] = len(group)
        merged["sample_sizes"] = [m[1]["sample_size"] for m in members if m[1].get("sample_size")]
        merged["member_ids"] = [m[1]["id"] for m in members]
        collapsed.append((rep_idx, merged))

    collapsed.sort(key=lambda pair: pair[0])
    return [merged for _, merged in collapsed]
