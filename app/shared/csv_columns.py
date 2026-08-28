"""app/shared/csv_columns.py — 匯入檔的欄名比對與數字容錯（共用層）。

原本住在 `app/ads/performance.py`，外殼切片刪掉 `app/ads/` 時搬過來：演算法本身跟廣告
無關（表頭 → 概念欄的兩階段比對、重複欄名去重、數字字串容錯），`app/orders/` 的
EasyStore 與蝦皮匯入一直是它的第二個呼叫端。共用層不得 import 任何分支專屬層
（見 `app/shared/web.py` 檔頭）。
"""


def _norm(name: str) -> str:
    return (name or "").strip().lower().replace(" ", "").replace("　", "")


def match_columns(headers: list, aliases_table: dict) -> tuple:
    """檔案表頭 → {概念欄: 實際欄名}，外加沒對上的欄位清單。

    兩階段比對（issue #23 bug 1）：先讓**所有**概念欄跑一輪「完全相等」，
    剩下沒中的概念欄才跑第二輪「前綴」比對。單階段寬鬆比對會讓「成果類型」（文字欄，
    前綴含「成果」）搶在「成果」（真正的轉換數字欄）之前被配走——完全相等優先，才不會被
    更長、只是恰好同前綴的欄名截胡。已配對的實際欄位一律排除，不會被下一個概念欄重複配。
    """
    mapping, used = {}, set()
    normalised = [(h, _norm(h)) for h in headers]

    def _match_pass(is_hit):
        for concept, aliases in aliases_table.items():
            if concept in mapping:
                continue
            for alias in aliases:
                target = _norm(alias)
                hit = next((original for original, norm_header in normalised
                            if original not in used and is_hit(norm_header, target)), None)
                if hit is not None:
                    mapping[concept] = hit
                    used.add(hit)
                    break

    _match_pass(lambda norm_header, target: norm_header == target)           # 第一輪：完全相等
    _match_pass(lambda norm_header, target: norm_header.startswith(target))  # 第二輪：前綴

    unmatched = [h for h in headers if h not in used]
    return mapping, unmatched


def dedupe_headers(headers: list) -> list:
    """重複欄名防禦（issue #23 bug 5）：匯出檔曾出現同一個欄名重複兩次。

    csv.DictReader 組列時用欄名當 key，同名欄位後面會蓋掉前面，其中一欄的資料會
    整批消失、比對也可能認錯欄。這裡在讀資料列之前把重複的欄名加上序號分開
    （第二次出現變成「欄名 (2)」），讓每一欄都留得住、配得到。
    """
    seen: dict = {}
    result = []
    for h in headers:
        seen[h] = seen.get(h, 0) + 1
        result.append(h if seen[h] == 1 else f"{h} ({seen[h]})")
    return result


def to_number(raw, cast=float):
    """把 CSV／xlsx 的數字字串轉成數字。容忍千分位逗號、幣別符號、空字串。"""
    if raw is None:
        return None
    text = str(raw).strip().replace(",", "").replace("$", "").replace("NT", "")
    if not text or text in ("-", "--"):
        return None
    try:
        return cast(float(text))
    except ValueError:
        return None
