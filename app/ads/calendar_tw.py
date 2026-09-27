"""app/ads/calendar_tw.py — F33-I02 (ruling 2A): the Taiwan calendar the strategy and delivery-plan
prompts read, as a hand-maintained literal table. Covers 2026–2027 only; extend it once a year
from the official sources (國定假日／補班: 人事總處 dgpa.gov.tw; 學測／分科: 大考中心 ceec.edu.tw;
國中會考: cap.rcpet.edu.tw; 統測: 技專測驗中心 tcte.edu.tw). Commerce peaks and school weeks are
conventions (`source: "convention"`), not official dates. Nothing here reads a clock or the
network: callers pass explicit dates, and a year outside `COVERED_YEARS` yields a note
(`coverage_note`) instead of an empty list that reads as "nothing happens". Private to app/ads.
"""

from datetime import date

KINDS = frozenset({"holiday", "makeup_workday", "exam", "commerce"})

COVERED_YEARS = frozenset({2026, 2027})

_DGPA_2026 = "https://www.dgpa.gov.tw/information?uid=2&pid=12574"
_DGPA_2027 = "https://www.dgpa.gov.tw/information?pid=12983&uid=2"
_CEEC = "ceec.edu.tw"
_CAP = "cap.rcpet.edu.tw"
_TCTE = "tcte.edu.tw"
_CONVENTION = "convention"
_CONVENTION_NOTE = "概略檔期，各校／各平台不同"


def _row(start: str, end: str, name: str, kind: str, source: str, note: str = "") -> dict:
    return {"start": start, "end": end, "name": name, "kind": kind, "source": source, "note": note}


def _convention(start: str, end: str, name: str, kind: str) -> dict:
    return _row(start, end, name, kind, _CONVENTION, _CONVENTION_NOTE)


# Verified official rows (lead's read of the sources above, 2026-09-27). No 補班 day in 2026 or
# 2027, so the table has no `makeup_workday` row yet -- the kind stays so a future year can add one.
EVENTS: list[dict] = [
    # ---- 2026 國定假日（人事總處 115 年辦公日曆表）----
    _row("2026-01-01", "2026-01-01", "元旦", "holiday", _DGPA_2026),
    _row("2026-02-14", "2026-02-22", "除夕及春節", "holiday", _DGPA_2026),
    _row("2026-02-27", "2026-03-01", "和平紀念日", "holiday", _DGPA_2026),
    _row("2026-04-03", "2026-04-06", "兒童節及清明節", "holiday", _DGPA_2026),
    _row("2026-05-01", "2026-05-03", "勞動節", "holiday", _DGPA_2026),
    _row("2026-06-19", "2026-06-21", "端午節", "holiday", _DGPA_2026),
    _row("2026-09-25", "2026-09-28", "中秋節及教師節", "holiday", _DGPA_2026),
    _row("2026-10-09", "2026-10-11", "國慶日", "holiday", _DGPA_2026),
    _row("2026-10-24", "2026-10-26", "光復節", "holiday", _DGPA_2026),
    _row("2026-12-25", "2026-12-27", "行憲紀念日", "holiday", _DGPA_2026),
    # ---- 2026 考季（官方日期）----
    _row("2026-01-17", "2026-01-19", "學測", "exam", _CEEC),
    _row("2026-04-25", "2026-04-26", "統測", "exam", _TCTE),
    _row("2026-05-16", "2026-05-17", "國中會考", "exam", _CAP),
    _row("2026-07-11", "2026-07-12", "分科測驗", "exam", _CEEC),
    # ---- 2026 慣例：學期週 ----
    _convention("2026-01-05", "2026-01-18", "期末考週", "exam"),
    _convention("2026-02-16", "2026-02-22", "開學週", "exam"),
    _convention("2026-04-13", "2026-04-26", "大學期中考週", "exam"),
    _convention("2026-06-08", "2026-06-21", "期末考週", "exam"),
    _convention("2026-09-07", "2026-09-13", "開學週", "exam"),
    _convention("2026-11-09", "2026-11-22", "大學期中考週", "exam"),
    # ---- 2026 慣例：檔期 ----
    _convention("2026-01-26", "2026-02-15", "春節送禮檔", "commerce"),  # 除夕 02-16 前三週
    _convention("2026-02-07", "2026-02-14", "情人節檔", "commerce"),
    _convention("2026-03-14", "2026-03-14", "白色情人節", "commerce"),
    _convention("2026-05-04", "2026-05-10", "母親節檔", "commerce"),
    _convention("2026-06-01", "2026-06-18", "618 年中慶", "commerce"),
    _convention("2026-08-01", "2026-08-08", "父親節檔", "commerce"),
    _convention("2026-08-19", "2026-08-19", "七夕", "commerce"),
    _convention("2026-09-11", "2026-09-24", "中秋送禮檔", "commerce"),  # 中秋 09-25 前兩週
    _convention("2026-11-01", "2026-11-11", "雙 11 檔", "commerce"),
    _convention("2026-12-01", "2026-12-12", "雙 12", "commerce"),
    _convention("2026-12-15", "2026-12-31", "聖誕跨年檔", "commerce"),
    # ---- 2027 國定假日（人事總處 116 年辦公日曆表）----
    _row("2027-01-01", "2027-01-03", "元旦", "holiday", _DGPA_2027),
    _row("2027-02-04", "2027-02-10", "除夕及春節", "holiday", _DGPA_2027),
    _row("2027-02-27", "2027-03-01", "和平紀念日", "holiday", _DGPA_2027),
    _row("2027-04-03", "2027-04-06", "兒童節及清明節", "holiday", _DGPA_2027),
    _row("2027-04-30", "2027-05-02", "勞動節", "holiday", _DGPA_2027),
    _row("2027-06-09", "2027-06-09", "端午節", "holiday", _DGPA_2027),
    _row("2027-09-15", "2027-09-15", "中秋節", "holiday", _DGPA_2027),
    _row("2027-09-28", "2027-09-28", "教師節", "holiday", _DGPA_2027),
    _row("2027-10-09", "2027-10-11", "國慶日", "holiday", _DGPA_2027),
    _row("2027-10-23", "2027-10-25", "光復節", "holiday", _DGPA_2027),
    _row("2027-12-24", "2027-12-26", "行憲紀念日", "holiday", _DGPA_2027),
    _row("2027-12-31", "2027-12-31", "年末補假", "holiday", _DGPA_2027, "117 年元旦補假"),
    # ---- 2027 考季（官方日期）----
    _row("2027-01-22", "2027-01-24", "學測", "exam", _CEEC),
    _row("2027-04-24", "2027-04-25", "統測", "exam", _TCTE),
    _row("2027-05-15", "2027-05-16", "國中會考", "exam", _CAP),
    _row("2027-07-10", "2027-07-11", "分科測驗", "exam", _CEEC),
    # ---- 2027 慣例：學期週 ----
    _convention("2027-01-05", "2027-01-18", "期末考週", "exam"),
    _convention("2027-02-15", "2027-02-21", "開學週", "exam"),
    _convention("2027-04-13", "2027-04-26", "大學期中考週", "exam"),
    _convention("2027-06-08", "2027-06-21", "期末考週", "exam"),
    _convention("2027-09-07", "2027-09-13", "開學週", "exam"),
    _convention("2027-11-09", "2027-11-22", "大學期中考週", "exam"),
    # ---- 2027 慣例：檔期 ----
    _convention("2027-01-15", "2027-02-04", "春節送禮檔", "commerce"),  # 除夕 02-05 前三週
    _convention("2027-02-07", "2027-02-14", "情人節檔", "commerce"),
    _convention("2027-03-14", "2027-03-14", "白色情人節", "commerce"),
    _convention("2027-05-03", "2027-05-09", "母親節檔", "commerce"),
    _convention("2027-06-01", "2027-06-18", "618 年中慶", "commerce"),
    _convention("2027-08-01", "2027-08-08", "父親節檔", "commerce"),
    _convention("2027-08-08", "2027-08-08", "七夕", "commerce"),
    _convention("2027-09-01", "2027-09-14", "中秋送禮檔", "commerce"),  # 中秋 09-15 前兩週
    _convention("2027-11-01", "2027-11-11", "雙 11 檔", "commerce"),
    _convention("2027-12-01", "2027-12-12", "雙 12", "commerce"),
    _convention("2027-12-15", "2027-12-31", "聖誕跨年檔", "commerce"),
]


def events_between(start: date, end: date) -> list[dict]:
    """Contract Q: rows `{start, end, name, kind, note}` (dates as `date`) overlapping
    [start, end], ordered by start. `source` stays in the table -- the prompt does not cite it."""
    rows = []
    for event in EVENTS:
        event_start = date.fromisoformat(event["start"])
        event_end = date.fromisoformat(event["end"])
        if event_start <= end and event_end >= start:
            rows.append({
                "start": event_start, "end": event_end, "name": event["name"],
                "kind": event["kind"], "note": event["note"],
            })
    rows.sort(key=lambda row: (row["start"], row["end"]))
    return rows


def coverage_note(start: date, end: date) -> str | None:
    """Contract Q: a sentence when any year of the range is outside the table, else None. The
    sentence tells the model the gap is a data gap, not a quiet period."""
    missing = [year for year in range(start.year, end.year + 1) if year not in COVERED_YEARS]
    if not missing:
        return None
    covered = f"{min(COVERED_YEARS)}～{max(COVERED_YEARS)}"
    missing_text = "、".join(str(year) for year in missing)
    return f"行事曆只涵蓋 {covered} 年，{missing_text} 年的假日與考季沒有資料，不要假設沒有活動。"


SECTION_HEADER = "【投放期間內的行事曆】"

_KIND_LABELS = {"holiday": "假日", "makeup_workday": "補班", "exam": "考季", "commerce": "檔期"}

EMPTY_LINE = "期間內沒有登記的假日、考季或檔期"


def _line(row: dict) -> str:
    when = row["start"].strftime("%m/%d")
    if row["end"] != row["start"]:
        when += "～" + row["end"].strftime("%m/%d")
    text = f"- {when} {row['name']}（{_KIND_LABELS[row['kind']]}）"
    return text + f"：{row['note']}" if row["note"] else text


def prompt_section(start: date | None, end: date | None) -> str:
    """The section both prompts append (strategy and delivery plan): header, one line per
    overlapping row or the explicit empty line, then the coverage note when one applies."""
    if start is None or end is None:
        return SECTION_HEADER + "\n期間還沒設定，對不上行事曆"
    rows = events_between(start, end)
    lines = [_line(row) for row in rows] or [EMPTY_LINE]
    note = coverage_note(start, end)
    if note is not None:
        lines.append(note)
    return SECTION_HEADER + "\n" + "\n".join(lines)
