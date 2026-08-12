# -*- coding: utf-8 -*-
"""app/intake/paste_parse.py — 貼回頁的免費規則驗證（DESIGN.md §19.7）。

零花費、零 LLM。只檢查五件事，不判斷內容對不對——那是人工逐條確認的工作（R5、R10）。
"""

import re

from app import mock_data as md

KIND_CATEGORY_SOURCE = {
    "品牌事實": md.BRAND_FACT_TYPES,
    "產品事實": md.PRODUCT_FACT_TYPES,
    "限制規則": md.RULE_TYPES,
    "宣稱": md.CLAIM_TYPES,
}
KIND_OPTIONS = list(KIND_CATEGORY_SOURCE.keys())
HEADER_COLUMNS = ["種類", "分類", "標題", "內容", "適用範圍", "佐證來源"]


def _split_row(line: str) -> list:
    return [p.strip() for p in line.split("|")]


# 從渲染後的畫面複製表格時，換行常被剪貼簿吃掉——整張表黏成一（少數幾）行。
# 「種類欄只有四種合法值、且一定接著｜」是可靠的列首特徵，用它把每一列重新切回來。
_ROW_START_RE = re.compile(r"(?:品牌事實|產品事實|限制規則|宣稱)\s*\|")
_HEADER_RE = re.compile(r"種類\s*\|\s*分類\s*\|\s*標題\s*\|\s*內容\s*\|\s*適用範圍\s*\|\s*佐證來源")


def maybe_reflow(raw_text: str) -> str:
    """換行遺失時重組表格；正常多行文字原樣返回。

    觸發條件：同一行裡出現兩個以上的列首特徵（正常情況一行最多一列）。
    ponytail: 啟發式重切——內容欄若剛好以種類字樣結尾接｜會誤切，該列會以欄數錯誤
    浮上來給人工看，不會悄悄吃掉資料。"""
    lines = raw_text.splitlines()
    if not any(len(_ROW_START_RE.findall(l)) >= 2 for l in lines):
        return raw_text
    m = _HEADER_RE.search(raw_text)
    if not m:
        return raw_text
    body = raw_text[m.end():]
    starts = [mm.start() for mm in _ROW_START_RE.finditer(body)]
    if not starts:
        return raw_text
    rows = []
    for i, s in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(body)
        rows.append(body[s:end].strip())
    return " | ".join(HEADER_COLUMNS) + "\n" + "\n".join(rows)


def count_data_lines(raw_text: str) -> int:
    """貼回頁錯誤 banner 要講「其餘 N 列沒問題」，用這個算表頭之後有幾列資料
    （沒找到表頭就是 0，呼叫端據此決定要不要顯示「沒有找到表格」的簡化版錯誤）。"""
    lines = [l for l in (raw.strip() for raw in raw_text.splitlines()) if l]
    for idx, line in enumerate(lines):
        if _split_row(line) == HEADER_COLUMNS:
            return len(lines) - idx - 1
    return 0


def parse_paste(raw_text: str, known_products: set, brand_name: str = None) -> tuple:
    """回傳 (rows, errors)。

    rows 為 None 表示驗證失敗；errors 為 [] 表示成功。成功時 rows 是
    [{"kind":, "category":, "title":, "content":, "scope":, "evidence":}, ...]，
    依貼上內容原本的列順序。

    容錯（Beast Gummy 事件的驗證端修正）：
    - 適用範圍寫成品牌名稱時自動當「整個品牌」，不報錯——外部 AI 最常這樣寫。
    - 其他不認得的名字仍擋下，但錯誤帶 unknown_scope 欄位，讓貼回頁能給
      「建立成新產品／歸到整個品牌」兩個出口，資料不整批丟失。"""
    lines = [l for l in (raw.strip() for raw in raw_text.splitlines()) if l]

    header_idx = None
    for idx, line in enumerate(lines):
        if _split_row(line) == HEADER_COLUMNS:
            header_idx = idx
            break
    if header_idx is None:
        return None, [{
            "line": None,
            "msg": "沒有找到表格。請確認貼上的內容裡有一列欄位名："
                   "種類｜分類｜標題｜內容｜適用範圍｜佐證來源，用「|」分隔。",
        }]

    data_lines = lines[header_idx + 1:]
    if not data_lines:
        return None, [{"line": None, "msg": "欄位名之後沒有任何資料列，沒有東西可以讀進來。"}]

    errors = []
    rows = []
    for i, line in enumerate(data_lines, start=1):
        parts = _split_row(line)
        if len(parts) != 6:
            errors.append({
                "line": i,
                "msg": f"第 {i} 列：這一列只有 {len(parts)} 欄，需要 6 欄。"
                       "可能是內容裡有「|」符號把欄位切開了。",
            })
            continue
        kind, category, title, content, scope, evidence = parts
        if kind not in KIND_OPTIONS:
            errors.append({
                "line": i,
                "msg": f"第 {i} 列：種類寫成「{kind}」。只能填：{ '、'.join(KIND_OPTIONS) }。",
            })
            continue
        allowed_categories = [label for _, label in KIND_CATEGORY_SOURCE[kind]]
        if category not in allowed_categories:
            errors.append({
                "line": i,
                "msg": f"第 {i} 列：分類寫成「{category}」。{kind}的分類只有："
                       f"{ '、'.join(allowed_categories) }。",
            })
            continue
        if brand_name and scope == brand_name.strip():
            scope = "整個品牌"
        if scope != "整個品牌" and scope not in known_products:
            errors.append({
                "line": i,
                "msg": f"第 {i} 列：適用範圍寫成「{scope}」。只能填「整個品牌」或你已經建立的產品名稱。",
                "unknown_scope": scope,
            })
            continue
        rows.append({
            "kind": kind, "category": category, "title": title, "content": content,
            "scope": scope, "evidence": evidence, "raw_row": line,
        })

    if errors:
        return None, errors
    return rows, []


def rewrite_scope(raw_text: str, name: str, new_scope: str) -> str:
    """把貼回文字裡「適用範圍＝name」的資料列改寫成 new_scope（歸到整個品牌用）。
    直接改在文字上，之後不論重驗幾次都不會忘記這個決定。HTML 表單與 JSON API 共用
    （票 B3-intake 從 routes.py `_rewrite_scope` 搬來）。"""
    out = []
    for line in raw_text.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 6 and parts[4] == name and parts != HEADER_COLUMNS:
            parts[4] = new_scope
            out.append(" | ".join(parts))
        else:
            out.append(line)
    return "\n".join(out)


def _demo() -> None:
    ok_text = (
        "種類 | 分類 | 標題 | 內容 | 適用範圍 | 佐證來源\n"
        "品牌事實 | 定位 | 價格帶 | 中高價位 | 整個品牌 | 官網\n"
        "產品事實 | 核心資訊 | 規格 | 一包 150 公克 | 烏龍茶包 | 官網"
    )
    rows, errors = parse_paste(ok_text, {"烏龍茶包"})
    assert errors == [] and len(rows) == 2, "格式正確時應解析出 2 列且無錯誤"

    bad_text = (
        "種類 | 分類 | 標題 | 內容 | 適用範圍 | 佐證來源\n"
        "品牌事實 | 功效 | 價格帶 | 中高價位 | 整個品牌 | 官網\n"
        "產品事實 | 核心資訊 | 規格 | 一包 150 公克\n"
        "宣稱 | 可用 | X | Y | 全系列 | 無"
    )
    rows, errors = parse_paste(bad_text, {"烏龍茶包"})
    assert rows is None and len(errors) == 3, "三種錯誤應各自回報，不是短路在第一個"
    assert errors[0]["line"] == 1 and "功效" in errors[0]["msg"]
    assert errors[1]["line"] == 2 and "4 欄" in errors[1]["msg"]
    assert errors[2]["line"] == 3 and "全系列" in errors[2]["msg"]

    no_table_rows, no_table_errors = parse_paste("這裡什麼表格都沒有", {"烏龍茶包"})
    assert no_table_rows is None and len(no_table_errors) == 1
    print("app/intake/paste_parse 自我檢查通過。")


if __name__ == "__main__":
    _demo()
