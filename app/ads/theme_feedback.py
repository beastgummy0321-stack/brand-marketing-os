# -*- coding: utf-8 -*-
"""成效回流給預選批次的純規則；真正的生成迴圈仍只有 theme_batch 一條。"""

from itertools import product

from app.ads import fingerprint as fp
from app.ads import nextcycle
from app.ads import onboarding
from app.ads import repository as ads_repo


# P1 配額規則（固定常數，不做學習率）：基準 2；可信且有轉換 +1；零轉換且花費達
# cell_trust_flags() 既有 50% 門檻 -1；樣本不足不加不減。多期資料只先累加再判一次，
# 不按期數重複加權；因此每格永遠落在 1～3 則。
BASE_THEME_QUOTA = 2
CONVERTING_THEME_BONUS = 1
UNDERPERFORMING_THEME_PENALTY = 1
MIN_THEME_QUOTA = 1
MAX_THEME_QUOTA = 3


def theme_quota(cell: dict, historical_cells: list) -> int:
    """用相同切角名稱的歷史成效調整預選數；沒有歷史時完整維持基準值。"""
    angle = (cell.get("creative_angle") or "").strip()
    matches = [row for row in historical_cells
               if angle and (row.get("creative_angle") or "").strip() == angle]
    if not matches:
        return BASE_THEME_QUOTA

    conversions = sum(float(row.get("conversions") or 0) for row in matches)
    spend = sum(float(row.get("spend") or 0) for row in matches)
    allocated_budget = sum(float(row.get("allocated_budget") or 0) for row in matches)
    flags = nextcycle.cell_trust_flags(conversions, spend, allocated_budget)

    # underperforming 雖會與 evidence_sufficient=False 同時出現，但既有定義明說「花過半仍
    # 零轉換」已是足夠的負面證據，因此先處理；其餘證據不足一律誠實中立。
    if flags.get("underperforming"):
        return max(MIN_THEME_QUOTA, BASE_THEME_QUOTA - UNDERPERFORMING_THEME_PENALTY)
    if flags.get("evidence_sufficient") is False:
        return BASE_THEME_QUOTA
    if conversions > 0:
        return min(MAX_THEME_QUOTA, BASE_THEME_QUOTA + CONVERTING_THEME_BONUS)
    return BASE_THEME_QUOTA


def _unique_fingerprints(fingerprints: list) -> list:
    unique = []
    seen = set()
    for fingerprint in fingerprints:
        normalized = fp.normalize(fingerprint)
        key = tuple(normalized.get(axis) for axis in fp.AXES)
        if normalized and key not in seen:
            seen.add(key)
            unique.append(normalized)
    return unique


def _farthest_same_format_fingerprint(history: list, format_key: str) -> dict:
    """封閉四軸的全組合中，挑與歷史最近鄰距離仍最大的那組；格式保持本批既定格式。"""
    values_by_axis = []
    for axis, spec in fp.AXES.items():
        if axis == "format":
            values_by_axis.append([format_key])
        else:
            values_by_axis.append(list(spec["values"]))
    candidates = [dict(zip(fp.AXES, values)) for values in product(*values_by_axis)]
    return max(candidates, key=lambda candidate: min(
        fp.distance(candidate, historical) for historical in history))


def anti_echo_summary(conn, brand_id: str, cycle_id: str, format_key: str):
    """最近一期亮回音室燈才回防撞衫摘要；新品牌或未亮燈都回 None。"""
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    previous = onboarding.previous_cycle(conn, brand_id, cycle) if cycle else None
    if previous is None or nextcycle.check_echo_chamber(
            conn, brand_id, previous["id"]) is None:
        return None

    history = _unique_fingerprints([
        fingerprint for fingerprint, _source_cycle_id in nextcycle.adopted_fingerprints(
            conn, brand_id, exclude_cycle_id=cycle_id)
    ])
    if not history:
        return None
    target = _farthest_same_format_fingerprint(history, format_key)
    return {
        "name": f"歷史已採用方向；這組刻意改用「{fp.describe(target)}」",
        "fingerprints": history,
    }
