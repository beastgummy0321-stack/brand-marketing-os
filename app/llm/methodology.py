# -*- coding: utf-8 -*-
"""app/llm/methodology.py — 方法論載入器（票 11，決策 0023/0024）。

生成計畫／素材時，把 app/methodology/README.md「任務型別 → 必讀方法論檔」對照表指定的
方法論內容組進 prompt。對照表是唯一權威——本檔不寫死任務型別對應哪些檔案，只負責解析表格、
讀檔、組字串；改對照表，行為就跟著變，不必改這裡的程式。

方法論檔缺失時優雅缺席（不擋生成流程）：跳過該檔，寫一筆 audit_log 供稽核
（principles 第 16 條「誠實狀態」；決策 0024 第 6 條）。
"""

import re
import sqlite3
from pathlib import Path
from typing import NamedTuple, Optional

from app.brand_intelligence import repository as repo
from app.core.audit import write_audit
from app.core.db import APP_DIR

METHODOLOGY_DIR = APP_DIR / "methodology"
README_PATH = METHODOLOGY_DIR / "README.md"

_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*(.+?)\s*\|\s*$")
# 檔名後可選加一個全形條件括號：`a.md`（需要：有商品）。開關名見
# app.brand_intelligence.repository.compute_methodology_switches 的四個中文鍵；
# 未知開關名一律不成立（優雅略過，同本檔對缺檔的處理哲學），不拋例外。
_FILE_RE = re.compile(r"`([^`]+\.md)`(?:（需要：([^）]+)）)?")
_TABLE_HEADING_MARKERS = ("任務型別", "必讀方法論檔")


def _parse_table_raw(readme_text: str) -> dict:
    """解析「任務型別 → 必讀方法論檔對照表」，回傳 {任務型別: [(檔名, 開關名或 None), ...]}。

    只在對應標題底下的表格生效，不誤吃檔案索引表（同一份 README 裡的另一張表）。
    """
    table: dict = {}
    in_section = False
    for line in readme_text.splitlines():
        if all(marker in line for marker in _TABLE_HEADING_MARKERS):
            in_section = True
            continue
        if not in_section:
            continue
        stripped = line.strip()
        if not stripped.startswith("|"):
            if table:  # 已經收集到資料列，遇到表格外的文字＝表格結束
                break
            continue
        m = _ROW_RE.match(stripped)
        if not m:
            continue
        label = m.group(1).strip()
        pairs = _FILE_RE.findall(m.group(2))  # [(檔名, 開關名或''), ...]
        if pairs:  # 表頭列／分隔列沒有 `xxx.md` 反引號，天然被排除
            table[label] = [(filename, condition or None) for filename, condition in pairs]
    return table


class MethodologyResult(NamedTuple):
    """compile() 的回傳值：text 進 prompt，missing_files 供呼叫端誠實標注在頁面上，
    loaded_files 是這次真的組進 prompt 的檔名（供呼叫端寫進 llm_task 稽核）。

    loaded_files 不能事後從 git 回推：拆檔＋條件載入之後，同一天同一份對照表，
    不同品牌的開關會載入不同的檔（ADR 0009）。不記下來這段歷史就補不回來。"""

    text: str
    missing_files: list
    loaded_files: list


def load_table_raw(readme_path: Path = README_PATH) -> dict:
    """讀取並解析對照表，回傳 {任務型別: [(檔名, 開關名或 None), ...]}——含條件的完整版，
    供 compile() 判斷過濾用。README 不存在時回傳空表（呼叫端優雅缺席，不擋流程）。"""
    if not readme_path.exists():
        return {}
    return _parse_table_raw(readme_path.read_text(encoding="utf-8"))


def load_table(readme_path: Path = README_PATH) -> dict:
    """讀取並解析對照表，回傳 {任務型別: [檔名, ...]}（不含條件，向後相容既有呼叫端）。"""
    return {label: [filename for filename, _condition in pairs]
            for label, pairs in load_table_raw(readme_path).items()}


def compile(
    conn: sqlite3.Connection,
    task_labels,
    *,
    brand_id: Optional[str] = None,
    actor: str = "system",
    methodology_dir: Optional[Path] = None,
    readme_path: Optional[Path] = None,
) -> MethodologyResult:
    """依任務型別（對照表中的中文列名）組出方法論內容區塊。

    task_labels：一個或多個對照表列名（例如素材生成同時吃「Hook／文案生成」與
    「圖片 Prompt 生成」兩列，取聯集、去重、保留順序）。
    對照表沒有該任務型別、或指定的檔案不存在，都優雅略過（不拋例外、不擋生成）；
    檔案缺失會寫一筆 audit_log（brand_id 可為 None＝系統級事件），且列進回傳值的
    missing_files，供呼叫端在頁面上誠實標注（決策 0024 第 6 條）。

    對照表列出的檔名可帶條件（（需要：X）），只有品牌對應開關成立才載入——見
    app.brand_intelligence.repository.compute_methodology_switches。
    brand_id=None 時不查開關、不過濾，帶條件的檔案跟其他檔案一樣全部載入。

    methodology_dir／readme_path 留 None 時在呼叫當下才解析模組層預設值
    （而非定義函式時就綁死），測試才能用 monkeypatch 換掉預設路徑。
    """
    table = load_table_raw(readme_path or README_PATH)
    methodology_dir = methodology_dir or METHODOLOGY_DIR
    switches: Optional[dict] = None  # 懶得算：沒有帶條件的檔案就不必查一次品牌資料
    filenames: list = []
    for label in task_labels:
        for filename, condition in table.get(label, []):
            if condition is not None and brand_id is not None:
                if switches is None:
                    switches = repo.compute_methodology_switches(conn, brand_id)
                if not switches.get(condition, False):
                    continue
            if filename not in filenames:
                filenames.append(filename)

    sections, missing, loaded = [], [], []
    for filename in filenames:
        path = methodology_dir / filename
        if not path.exists():
            write_audit(
                conn, brand_id=brand_id, entity_type="methodology_file", entity_id=filename,
                action="missing", actor=actor,
                after={"task_labels": list(task_labels)},
                reason=f"對照表指定的方法論檔缺失，已優雅略過（不擋生成）：{filename}",
            )
            missing.append(filename)
            continue
        content = path.read_text(encoding="utf-8").strip()
        sections.append(f"【方法論：{filename}】\n{content}")
        loaded.append(filename)

    return MethodologyResult(text="\n\n".join(sections), missing_files=missing,
                             loaded_files=loaded)
