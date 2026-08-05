# -*- coding: utf-8 -*-
"""app/core/cleanup.py — 品牌刪除的清理登記處（第 2 刀「清理登記處」）。

刪品牌時要連鎖清掉各模組掛在該品牌下的資料。以前是 app/brand_intelligence/routes.py
手寫死「要通知誰」，漏了誰就沒人清（ads 就是這樣漏掉的）。改成登記制：各模組在自己
的 repository.py 檔尾呼叫 register()，把「清點函式＋清除函式」登記進來；本檔不知道
任何模組的實作細節，不 import 任何 app 模組，只負責把登記的名單串起來。

Q4 單一交易、全有全無：delete_all() 只下 DELETE、絕對不 commit，commit 由呼叫端
（品牌永久層 delete_brand）統一做一次，任何一個模組出錯就整批回捲。
"""

_REGISTRY: dict = {}


def register(name, *, count_brand, delete_brand, brand_tables) -> None:
    """四個都必填，缺一個就當場報錯；同一個 name 不能重複登記。用 * 強制具名參數，
    之後要加 count_product／delete_product 時不用回頭改已經寫好的登記呼叫。

    brand_tables 是「刪品牌時本模組會清掉哪些資料表」的表名集合。它不參與刪除
    （刪除走 delete_brand），存在的唯一理由是讓涵蓋率警報器
    （app/tests/test_cleanup_coverage.py）有一份真相可以比對——資料庫裡冒出新的
    帶 brand_id 的表卻沒人認領時，測試要能自己叫。宣告在這裡而不是另外維護一份
    清單，是因為「另外維護一份清單」正是這整串 bug 的根因。
    """
    if not name or count_brand is None or delete_brand is None or brand_tables is None:
        raise ValueError("register() 的 name、count_brand、delete_brand、brand_tables 都是必填")
    if name in _REGISTRY:
        raise ValueError(f"「{name}」已經登記過清理函式了，不能重複登記")
    _REGISTRY[name] = {
        "count_brand": count_brand,
        "delete_brand": delete_brand,
        "brand_tables": frozenset(brand_tables),
    }


def registered_names() -> list:
    """給 main.py 的啟動斷言用：確認該登記的模組都登記了。"""
    return list(_REGISTRY)


def declared_brand_tables() -> dict:
    """給涵蓋率警報器用：{模組名稱: 它宣告會清掉的表名集合}。"""
    return {name: entry["brand_tables"] for name, entry in _REGISTRY.items()}


def count_all(conn, brand_id: str) -> list:
    """給刪除確認頁用：把各登記模組回傳的 [(標籤, 筆數)] 串成一份清單。"""
    rows = []
    for entry in _REGISTRY.values():
        rows.extend(entry["count_brand"](conn, brand_id))
    return rows


def delete_all(conn, brand_id: str) -> dict:
    """呼叫所有登記模組的清除函式。只下 DELETE，絕對不 commit——commit 由呼叫端
    在做完品牌本身的刪除、寫完稽核之後統一做一次（Q4 單一交易、全有全無）。"""
    counts = {}
    for entry in _REGISTRY.values():
        counts.update(entry["delete_brand"](conn, brand_id))
    return counts
