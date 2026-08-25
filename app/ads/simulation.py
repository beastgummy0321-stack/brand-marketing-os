# -*- coding: utf-8 -*-
"""app/ads/simulation.py — 紙上模擬第 0 期（票 14）。

新品牌第一次開廣告時，先零成本走完一整圈：計畫 → 素材 → 假成效 → 判讀。
目的是讓完全沒投過廣告的人先知道「這個系統會給我什麼、我要做什麼決定」，
而不是拿真錢去學。

## 為什麼幾乎沒有新程式碼

模擬期就是一個一般的廣告檔期，只有三點不同：
1. `phase='simulation'`——所有頁面據此標示「這是模擬」。
2. 成效數字由本檔產生，`source='simulated'`，不是真的花錢跑出來的。
3. 不產投放交接包——模擬期不該讓人真的拿去 Meta 貼。

計畫與素材照樣走真實管線（那本來就是產品價值所在，也讓人看到真實品質）。

## 數字怎麼來

由程式從基準值加隨機波動算出（決策 0022 第 22 點，不讓 LLM 編——它很會編出
不可能的投報率）。基準的優先序：這個品牌自己的歷史 > 產業通例值，
兩者都會在畫面上標明用的是哪一種。

亂數以 `cycle_id` 當種子，所以同一期重看永遠是同一組數字（不會每次重整就變一個結果），
不同期之間又不一樣。
"""

import random
from typing import Optional

from app.ads import budget as budget_calc
from app.ads import performance as ads_performance
from app.ads import performance_batches
from app.ads import reading as ads_reading
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi
from app.core.db import new_id, now_utc, DEV_ORG_ID

# 產業通例值。只在這個品牌完全沒有歷史時使用，畫面必須標明來源。
INDUSTRY_CTR = 0.012          # 點擊率 1.2%
INDUSTRY_CPC = 12.0           # 每次點擊約 12 元
INDUSTRY_CONVERSION_RATE = 0.02  # 點進來的人有 2% 會買

WOBBLE = 0.35  # 上下隨機浮動的幅度：真實投放本來就不會剛好落在平均值上

SIMULATION_NOTE = (
    "以下數字是模擬的，不是真實投放結果。用途是讓你先看看一期跑完會拿到什麼，"
    "不代表你的廣告實際會有這樣的表現。"
)


def _basis(conn, brand_id: str, exclude_cycle_id: Optional[str] = None) -> tuple:
    """回 (基準 dict, 來源說明)。有自己的歷史就用自己的。

    exclude_cycle_id 要傳當期——否則第一期會拿自己剛跑出來的數字當「過去的表現」，
    畫面上就會謊稱有歷史依據（截圖驗收時抓到的問題）。
    """
    baseline = ads_reading.brand_baseline(conn, brand_id, exclude_cycle_id=exclude_cycle_id)
    if baseline.get("ctr") and baseline.get("cpc"):
        return ({"ctr": baseline["ctr"], "cpc": baseline["cpc"],
                 "conversion_rate": INDUSTRY_CONVERSION_RATE},
                "依據這個品牌過去的實際表現")
    return ({"ctr": INDUSTRY_CTR, "cpc": INDUSTRY_CPC,
             "conversion_rate": INDUSTRY_CONVERSION_RATE},
            "依據產業通例值（這個品牌還沒有自己的數字）")


def simulate_totals(cycle: dict, basis: dict, *, average_price: Optional[float] = None) -> dict:
    """產生一組模擬成效。同一個 cycle_id 永遠得到同一組數字。"""
    rng = random.Random(cycle["id"])

    def wobble(value: float) -> float:
        return value * (1 + rng.uniform(-WOBBLE, WOBBLE))

    spend = round(cycle["budget"] or 0, 2)
    cpc = max(wobble(basis["cpc"]), 1.0)
    clicks = int(spend / cpc) if cpc else 0
    ctr = max(wobble(basis["ctr"]), 0.0005)
    impressions = int(clicks / ctr) if ctr else 0
    conversions = int(clicks * max(wobble(basis["conversion_rate"]), 0.0))
    revenue = round(conversions * (average_price or 0), 2)

    return {"impressions": impressions, "clicks": clicks, "spend": spend,
            "conversions": conversions, "revenue": revenue}


def _average_price(conn, brand_id: str, cycle_id: str) -> float:
    prices = []
    for allocation in ads_repo.list_cycle_products(conn, brand_id, cycle_id):
        economics = bi.get_product_economics(conn, brand_id, allocation["product_id"])
        if economics and economics.get("selling_price"):
            prices.append(float(economics["selling_price"]))
    if prices:
        return sum(prices) / len(prices)
    # 沒有售價資料時給一個保守的假設值，並在畫面上說明模擬用的是假設數字
    return 800.0


def generate(conn, brand_id: str, cycle_id: str, actor: str) -> tuple:
    """替模擬檔期產生一筆假成效。成功回 (True, 來源說明)。"""
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if cycle is None:
        raise ValueError("找不到廣告檔期")
    if cycle["phase"] != "simulation":
        return False, "這不是模擬檔期，成效要用真實資料。"

    basis, basis_note = _basis(conn, brand_id, exclude_cycle_id=cycle_id)
    totals = simulate_totals(cycle, basis,
                             average_price=_average_price(conn, brand_id, cycle_id))

    ts = now_utc()
    # 走共用刪除入口，它會先清掉掛在上面的 derived_metric（先子後父）
    performance_batches.delete_snapshots(conn, brand_id, cycle_id, source="simulated")
    # 票 11 D3：模擬成效沒有廣告可對——沒有 publishing_package，`resolve_product_id`
    # 的 a／b 兩條路都用不上；原本設計的選項 c（檔期只賣一個產品就算那個的）已經拿掉
    # （見 performance.resolve_product_id 的說明），所以這裡呼叫它一定回 None，
    # 不必真的呼叫，直接留 NULL 比較誠實（鐵則 16：模稜兩可不猜）。
    conn.execute(
        "INSERT INTO performance_snapshot (id, org_id, brand_id, campaign_cycle_id, product_id,"
        " platform, date_range_start, date_range_end, as_of_date, snapshot_taken_at,"
        " currency, impressions, clicks, spend, conversions, revenue, reconciled, source,"
        " import_batch_id, quarantined, created_at)"
        " VALUES (%s, %s, %s, %s, NULL, 'meta', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, 'simulated', %s, 0, %s)",
        (new_id("psn"), DEV_ORG_ID, brand_id, cycle_id, cycle["start_date"], cycle["end_date"],
         cycle["end_date"], ts, cycle["currency"], totals["impressions"], totals["clicks"],
         totals["spend"], totals["conversions"], totals["revenue"], f"sim_{ts}", ts),
    )
    conn.commit()
    ads_performance.save_derived_metrics(conn, brand_id, cycle_id)
    return True, basis_note


def is_simulation(cycle: Optional[dict]) -> bool:
    return bool(cycle and cycle.get("phase") == "simulation")


def offer_simulation(conn, brand_id: str) -> bool:
    """要不要提供模擬入口：這個品牌一期都還沒跑過才提供（跑過就別擋熟手的路）。"""
    return not ads_repo.has_any_cycle(conn, brand_id)
