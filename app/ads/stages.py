# -*- coding: utf-8 -*-
"""app/ads/stages.py — 檔期進度軌五格階段推導（D線票1，GitHub issue #43）。

進度軌五格＝計畫／素材／交接包／投放前檢查／成效。單看 campaign_cycle.status 分不出
中間三格——素材、交接包、投放前檢查同屬 PRODUCTION 這一個狀態窗口（見 app/ads/routes.py
CYCLE_STATUS_LABELS）。要分出這三格，必須併用 app/ads/routes.py 的 ads_cycle() 路由
現況已經在算的既有訊號：素材是否已採用（has_adopted）、交接包是否已建置
（package_count，見 app/ads/handoff.build_packages）／已啟用（activated_count，
見 app/ads/handoff.authorize_and_map）。不新增任何資料庫欄位。

投放前檢查清單完成度（app/ads/checklist.completeness）刻意不當成推進到下一格的關卡：
checklist.py 的既有設計原則是「兩類都不擋流程」（決策 0013），這裡比照辦理——清單
完不完成不影響階段判讀，只是投放前檢查這一格底下可另外顯示的細節，不是分界條件。
"""

STAGE_LABELS = ["計畫", "素材", "交接包", "投放前檢查", "成效"]

# 對齊 app/ads/routes.py 的 CYCLE_STATUS_LABELS。PLANNING／PLAN_SELECT／REVIEW
# 與任何未知狀態都落在 derive_stage() 最後的 fallback（計畫格），不需要另外列出。
_POST_PRODUCTION_STATUSES = ("LIVE", "EVALUATING", "CLOSED")


def derive_stage(cycle_status: str, *, has_adopted: bool = False,
                  package_count: int = 0, activated_count: int = 0) -> int:
    """回傳這期檔期目前落在五格中的第幾格（1-5，對應 STAGE_LABELS）。

    - 已有交接包啟用（activated_count > 0）就直接算成效格：就算 cycle_status
      因為某種原因還沒同步過來，「已啟用」本身就代表已經在投放。
    - 狀態在 LIVE／EVALUATING／CLOSED：成效格。
    - 狀態是 PRODUCTION：素材沒採用＝素材格；採用了但交接包還沒建＝交接包格；
      交接包建好了＝投放前檢查格（在這裡等人去 Meta 開通）。
    - 其餘狀態（PLANNING／PLAN_SELECT／REVIEW，或未知狀態一律當作還沒進production）＝計畫格。
    """
    if activated_count > 0 or cycle_status in _POST_PRODUCTION_STATUSES:
        return 5
    if cycle_status == "PRODUCTION":
        if not has_adopted:
            return 2
        if package_count == 0:
            return 3
        return 4
    return 1


def demo() -> None:
    """python -m app.ads.stages —— 純函數的最小自檢（無需資料庫）。"""
    assert derive_stage("PLANNING") == 1
    assert derive_stage("PLAN_SELECT") == 1
    assert derive_stage("REVIEW") == 1
    assert derive_stage("PRODUCTION", has_adopted=False) == 2
    assert derive_stage("PRODUCTION", has_adopted=True, package_count=0) == 3
    assert derive_stage("PRODUCTION", has_adopted=True, package_count=1) == 4
    assert derive_stage("PRODUCTION", has_adopted=True, package_count=2, activated_count=1) == 5
    assert derive_stage("LIVE") == 5
    assert derive_stage("EVALUATING") == 5
    assert derive_stage("CLOSED") == 5
    print("stages 自檢通過")


if __name__ == "__main__":
    demo()
