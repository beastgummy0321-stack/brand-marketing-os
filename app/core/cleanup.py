# -*- coding: utf-8 -*-
"""app/core/cleanup.py — 品牌／產品刪除的清理登記處（第 2 刀「清理登記處」，
第 6 刀加上產品維度）。

刪品牌／刪產品時要連鎖清掉各模組掛在底下的資料。以前是各模組的 routes.py／repository.py
手寫死「要通知誰」，漏了誰就沒人清（ads 就是這樣漏掉的）。改成登記制：各模組在自己
的 repository.py 檔尾呼叫 register()，把「清點函式＋清除函式」登記進來；本檔不知道
任何模組的實作細節，不 import 任何 app 模組，只負責把登記的名單串起來。

Q4 單一交易、全有全無：delete_all()／delete_all_product() 只下 DELETE、絕對不 commit，
commit 由呼叫端（品牌永久層 delete_brand／delete_product）統一做一次，任何一個模組
出錯就整批回捲。
"""

_REGISTRY: dict = {}


def register(name, *, count_brand, delete_brand, brand_tables,
             count_product, delete_product, product_tables) -> None:
    """品牌維度三參數（count_brand／delete_brand／brand_tables）必填，同一個 name 不能
    重複登記。用 * 強制具名參數。

    產品維度三參數（count_product／delete_product／product_tables）同樣必填——但「必填」
    指的是「一定要傳，不能省略參數」，不是「一定要有值」：本模組若根本沒有產品層資料
    （例如建檔精靈、中斷提醒、訂單），就明確傳 count_product=None、delete_product=None、
    product_tables=frozenset() 表示「我確實沒有」，而不是讓呼叫端偷懶省略——省略等於
    又回到「有清點沒清除」那個根因（呼叫端可能忘記某模組其實有產品層資料，卻因為
    參數選填而沒被逼著想一遍）。

    一致性檢查，宣告了表就必須給函式、給了函式就必須宣告表，兩邊對不上當場報錯：
      - count_product／delete_product 必須同時給、或同時不給（只給一個代表另一個大概
        是漏寫了）。
      - product_tables 是否非空，必須跟「有沒有給 count_product／delete_product」一致：
        宣告了表卻沒給函式，清掉不了那些表；給了函式卻不宣告表，涵蓋率警報器
        （app/tests/test_cleanup_coverage.py）就比對不到，形同白登記。

    brand_tables／product_tables 是「刪品牌／刪產品時本模組會清掉哪些資料表」的表名
    集合。它們不參與刪除（刪除走 delete_brand／delete_product 本身），存在的唯一理由
    是讓涵蓋率警報器有一份真相可以比對——資料庫裡冒出新的帶 brand_id／product_id 的表
    卻沒人認領時，測試要能自己叫。宣告在這裡而不是另外維護一份清單，是因為「另外維護
    一份清單」正是這整串 bug 的根因。
    """
    if not name or count_brand is None or delete_brand is None or brand_tables is None:
        raise ValueError("register() 的 name、count_brand、delete_brand、brand_tables 都是必填")
    if product_tables is None:
        raise ValueError(
            f"「{name}」的 product_tables 為必填：沒有產品層資料就明確傳 frozenset()，"
            "不要省略參數")
    count_given = count_product is not None
    delete_given = delete_product is not None
    if count_given != delete_given:
        raise ValueError(f"「{name}」的 count_product 與 delete_product 必須同時給、或同時不給")
    if bool(product_tables) != count_given:
        raise ValueError(
            f"「{name}」的 product_tables 跟 count_product／delete_product 不一致：宣告了表"
            "就必須給函式，給了函式就必須宣告表")
    if name in _REGISTRY:
        raise ValueError(f"「{name}」已經登記過清理函式了，不能重複登記")
    _REGISTRY[name] = {
        "count_brand": count_brand,
        "delete_brand": delete_brand,
        "brand_tables": frozenset(brand_tables),
        "count_product": count_product,
        "delete_product": delete_product,
        "product_tables": frozenset(product_tables),
    }


def registered_names() -> list:
    """給 main.py 的啟動斷言用：確認該登記的模組都登記了。"""
    return list(_REGISTRY)


def declared_brand_tables() -> dict:
    """給涵蓋率警報器用：{模組名稱: 它宣告會清掉的表名集合}。"""
    return {name: entry["brand_tables"] for name, entry in _REGISTRY.items()}


def declared_product_tables() -> dict:
    """給涵蓋率警報器用：{模組名稱: 它宣告會清掉的產品層表名集合}。沒有產品層資料的
    模組值是空集合，仍會出現在這份字典裡（register() 強制每個模組都要明確表態）。"""
    return {name: entry["product_tables"] for name, entry in _REGISTRY.items()}


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


def count_all_product(conn, brand_id: str, product_id: str) -> list:
    """給刪除確認頁用：把各登記模組回傳的 [(標籤, 筆數)] 串成一份清單。沒有產品層資料
    的模組（count_product 是 None）直接跳過。"""
    rows = []
    for entry in _REGISTRY.values():
        if entry["count_product"] is not None:
            rows.extend(entry["count_product"](conn, brand_id, product_id))
    return rows


def delete_all_product(conn, brand_id: str, product_id: str) -> dict:
    """呼叫所有登記模組的產品層清除函式。只下 DELETE，絕對不 commit——commit 由呼叫端
    在做完產品本身的刪除、寫完稽核之後統一做一次（Q4 單一交易、全有全無）。沒有產品層
    資料的模組（delete_product 是 None）直接跳過。"""
    counts = {}
    for entry in _REGISTRY.values():
        if entry["delete_product"] is not None:
            counts.update(entry["delete_product"](conn, brand_id, product_id))
    return counts
