# -*- coding: utf-8 -*-
"""app/dashboard/health.py — 品牌健康度燈號（票 02-overview-cards，規格 0001）。

純函數：資料進、結論出，不碰資料庫、不呼叫 LLM（沿用判讀狀態機模式）。
規則第一版（規格「健康度燈號第一版」）：有未結 money_loss 警報＝紅、
有未結 rule_warning 警報＝黃、其餘綠。money_loss 優先於 rule_warning。
"""

from typing import Iterable

RED, YELLOW, GREEN = "red", "yellow", "green"


def brand_health(open_interrupt_severities: Iterable[str]) -> str:
    severities = set(open_interrupt_severities)
    if "money_loss" in severities:
        return RED
    if "rule_warning" in severities:
        return YELLOW
    return GREEN


def demo() -> None:
    """python -m app.dashboard.health —— 純函數的最小自檢（無需資料庫）。"""
    assert brand_health([]) == GREEN
    assert brand_health(["informational"]) == GREEN
    assert brand_health(["irreversible"]) == GREEN
    assert brand_health(["rule_warning"]) == YELLOW
    assert brand_health(["money_loss"]) == RED
    assert brand_health(["money_loss", "rule_warning"]) == RED  # 紅優先於黃
    print("dashboard.health 自檢通過")


if __name__ == "__main__":
    demo()
