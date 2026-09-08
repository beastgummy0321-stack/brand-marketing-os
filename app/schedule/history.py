"""app/schedule/history.py — 票 past-ads/03（ADR 0067）：讀老廣告的成效排名（純算術），
把最需要被問的那批廣告的素材快取進 `imported_ad`，讓 owner 自己標七維座標。私有：只有
`app/schedule/routes.py`／`app/schedule/__init__.py`（延遲 import）呼叫本檔。

ADR 0067 rule 1：**沒有任何一支 LLM 呼叫**——本檔全部是算術＋一支 Graph 素材讀取，
「哪個座標讓這則廣告贏／輸」永遠問 owner，不問模型。本檔不 import `app.llm` 的任何一支
（那個字本身這裡也不出現，票面那條 grep 認的是它），不建立、不讀寫 `rule` 表。
"""

from datetime import timedelta

from app.background import is_active as background_is_active
from app.brand_intelligence import repository as bi_repo
from app.core.audit import write_audit
from app.core.db import now_utc
from app.meta import daily_pull, graph
from app.meta import repository as meta_repo
from app.schedule import diagnosis as diagnosis_mod
from app.schedule import performance as performance_mod
from app.schedule import repository as schedule_repo
from app.schedule.creative import COORDINATE_KEYS

_TOP_N = 5
_MAX_CARDS_PER_CURRENCY = 15


def _rank_cards(rows_by_ad: dict, names_and_cpa: dict) -> list[dict]:
    """一個幣別內的逐日花費列（已經照 `entity_id` 分好組）→ ADR 0067 §1.7 那三張榜單的
    聯集：花費前 5、保守 ROAS 前 5（只在有追蹤到營收的廣告裡選）、樂觀 ROAS 最後 5（同一個
    篩選）——union 順序固定 top_spend → top_roas → bottom_roas，用 `entity_id` 去重，最多
    15 張卡，`why` 記錄一張卡是被哪幾張榜單選中的（可能不只一張）。

    每張卡的花費／ROAS 數字整組借 `performance._bucket()`（reuse, do not reimplement，
    票面原話）——這裡只加 `first_seen_date`／`last_seen_date`（這個廣告在這個視窗裡最早／
    最晚一天的 `spend_date`）跟 `name`／`cpa`（來自 `spend_summary()` 那份既有聚合，同一批
    讀取 `performance.ad_performance()` 也是這樣接）。"""
    cards: dict[str, dict] = {}
    for entity_id, ad_rows in rows_by_ad.items():
        bucket = performance_mod._bucket(ad_rows)
        name, cpa = names_and_cpa.get(entity_id, (entity_id, None))
        dates = [r["spend_date"] for r in ad_rows]
        cards[entity_id] = {
            "external_id": entity_id, "name": name, "cpa": cpa,
            "first_seen_date": min(dates), "last_seen_date": max(dates),
            "spend": bucket["spend"], "impressions": bucket["impressions"],
            "clicks": bucket["clicks"], "revenue": bucket["revenue"],
            "roas": bucket["roas"], "roas_conservative": bucket["roas_conservative"],
            "roas_coverage": bucket["roas_coverage"],
        }

    with_revenue = [c for c in cards.values() if c["revenue"] is not None]
    lists = (
        ("top_spend", sorted(cards.values(), key=lambda c: -c["spend"])[:_TOP_N]),
        ("top_roas", sorted(with_revenue, key=lambda c: -c["roas_conservative"])[:_TOP_N]),
        ("bottom_roas", sorted(with_revenue, key=lambda c: c["roas"])[:_TOP_N]),
    )
    ordered: list[dict] = []
    seen: dict[str, dict] = {}
    for why, group in lists:
        for card in group:
            existing = seen.get(card["external_id"])
            if existing is None:
                new_card = {**card, "why": [why]}
                seen[card["external_id"]] = new_card
                ordered.append(new_card)
            else:
                existing["why"].append(why)
    return ordered[:_MAX_CARDS_PER_CURRENCY]


def _verdict(card: dict, breakeven: float | None) -> str:
    """ADR 0066 rule 4 的算術，套進 ADR 0067 §1.7 的問法：`win` 保守 ROAS 過線，`lose`
    樂觀 ROAS 都不過線，其餘（含沒有打平線、沒有追蹤到營收）都是 `unclear`——絕不讓一張
    卡在「不知道」跟「輸」之間含糊。"""
    if breakeven is None or card["revenue"] is None:
        return "unclear"
    if card["roas_conservative"] >= breakeven:
        return "win"
    if card["roas"] < breakeven:
        return "lose"
    return "unclear"


def _coordinates_from_row(row: dict | None) -> dict:
    if row is None:
        return {dimension: None for dimension in COORDINATE_KEYS}
    return {dimension: row[f"{dimension}_key"] for dimension in COORDINATE_KEYS}


def _needs_creative_fetch(existing_by_id: dict, external_id: str) -> bool:
    row = existing_by_id.get(external_id)
    return row is None or row["creative_fetched_at"] is None


def _attach_creative(conn, org_id: str, brand_id: str, cards: list[dict],
                      existing_by_id: dict) -> None:
    """ADR 0067 §1.9：這個視窗要問的每一張卡，素材只抓一次——已經有快取（`imported_ad`
    列存在且 `creative_fetched_at` 不是 NULL）的卡不再問 Meta。一次 `fetch_ad_creatives`
    打完整批 id（不是逐卡各打一次），失敗就整批卡 `creative: null` 帶錯誤訊息，**不寫任何
    一列**（本檔 module docstring／ticket 矛盾檢查段：GET 的寫入只有這支快取 upsert，
    失敗就是零列，不能半套）。成功則每一個 id（含 Meta 答 `None` 的那個）都落地一列，
    `creative_fetched_at` 蓋起來，下一次 GET 就不會再問——`None` 本身就是「Meta 現在回不出
    這則的素材」那個狀態，不是還沒查過。"""
    needs_fetch = [c for c in cards if _needs_creative_fetch(existing_by_id, c["external_id"])]
    error_message: str | None = None
    if needs_fetch:
        token = meta_repo.get_token(conn, org_id)
        if token is None:
            # 比照 app/meta/repository.py 既有的 `token is None` 慣例（那裡回退成空清單，
            # 這裡沒有清單可退，只能整批當「這次問不到」處理，跟 GraphError 同一條路）。
            error_message = "還沒有連上 Meta 的權杖，無法讀取素材。"
        else:
            try:
                answers = graph.fetch_ad_creatives(token, [c["external_id"] for c in needs_fetch])
            except graph.GraphError as exc:
                error_message = str(exc)
            else:
                ad_channel_id = schedule_repo.ensure_meta_channel(conn, org_id)
                for card in needs_fetch:
                    answer = answers.get(card["external_id"]) or {}
                    row = schedule_repo.upsert_imported_ad(
                        conn, org_id=org_id, brand_id=brand_id, ad_channel_id=ad_channel_id,
                        external_id=card["external_id"], external_name=card["name"],
                        first_seen_date=card["first_seen_date"],
                        last_seen_date=card["last_seen_date"],
                        creative_body=answer.get("body"), creative_title=answer.get("title"),
                        creative_image_url=answer.get("image_url"), creative_fetched_at=now_utc(),
                        coordinates_status="pending",
                    )
                    existing_by_id[card["external_id"]] = row
                conn.commit()

    needs_fetch_ids = {c["external_id"] for c in needs_fetch}
    for card in cards:
        if card["external_id"] in needs_fetch_ids and error_message is not None:
            card["creative"] = None
            card["creative_error"] = error_message
            continue
        card["creative_error"] = None
        row = existing_by_id.get(card["external_id"])
        if row is None:
            card["creative"] = None
        else:
            body = row["creative_body"]
            title = row["creative_title"]
            image_url = row["creative_image_url"]
            card["creative"] = (
                {"body": body, "title": title, "image_url": image_url}
                if (body or title or image_url) else None
            )


def _card_view(card: dict, row: dict | None) -> dict:
    return {
        "external_id": card["external_id"], "name": card["name"], "why": card["why"],
        "first_seen_date": card["first_seen_date"], "last_seen_date": card["last_seen_date"],
        "spend": card["spend"], "impressions": card["impressions"], "clicks": card["clicks"],
        "revenue": card["revenue"], "roas": card["roas"],
        "roas_conservative": card["roas_conservative"], "roas_coverage": card["roas_coverage"],
        "cpa": card["cpa"], "verdict": card["verdict"],
        "creative": card["creative"], "creative_error": card["creative_error"],
        "coordinates": _coordinates_from_row(row),
        "coordinates_status": row["coordinates_status"] if row else "pending",
        "owner_note": row["owner_note"] if row else None,
    }


def _tag_view(row: dict) -> dict:
    """PUT `.../history/{external_id}` 回的窄形狀（票面「Reply」段）——不是整包卡片，
    只回被改動的那五個欄位。"""
    return {
        "external_id": row["external_id"], "coordinates": _coordinates_from_row(row),
        "coordinates_status": row["coordinates_status"], "owner_note": row["owner_note"],
        "tagged_at": row["tagged_at"],
    }


def history_cards(conn, org_id: str, brand_id: str) -> dict:
    """票 past-ads/03（ADR 0067）：投放史頁面整包——連了哪些帳號、補拉進度、打平線、
    逐幣別的廣告排行卡，外加座標詞彙給標籤下拉選單用。沒有任何一步猜「為什麼」，
    「為什麼」永遠是 `tag_imported_ad` 讓 owner 自己填的那一句話。"""
    account_ids = meta_repo.bound_account_ids_for_brand(conn, org_id, brand_id)
    all_coordinates = schedule_repo.list_coordinates(conn, org_id, brand_id)
    coordinates = [c for c in all_coordinates if c["disabled_at"] is None]
    if not account_ids:
        return {
            "connected": False, "backfill": None, "breakeven": None, "currencies": [],
            "coordinates": coordinates,
        }

    status = daily_pull.backfill_status(conn, org_id, account_ids)
    backfill = {"running": background_is_active(daily_pull.backfill_lock(org_id)), **status}
    # `breakeven_roas()` 的既有慣例（`diagnosis.brand_diagnosis_response` 一樣的包法）：
    # 永遠是一個物件，`roas` 才是可能 None 的那個欄位（沒有毛利率可算時），`source` 一律有
    # 一句話可說（"還沒有毛利率"）。`breakeven: null` 只在最上面「還沒連 Meta 帳號」那個
    # early return 出現，這裡連過帳號就一定有物件可包。
    breakeven_value, breakeven_source = diagnosis_mod.breakeven_roas(conn, org_id, brand_id)
    breakeven = {"roas": breakeven_value, "source": breakeven_source}

    currencies: list[dict] = []
    if status["earliest_spend_date"] is not None:
        since = status["earliest_spend_date"]
        until = status["latest_spend_date"] + timedelta(days=1)
        conversion_goal = (bi_repo.get_brand(conn, brand_id) or {}).get("conversion_goal")
        daily_rows = meta_repo.daily_entity_spend(
            conn, org_id, account_ids, since, until, level="ad",
        )
        summary = meta_repo.spend_summary(
            conn, org_id, account_ids, since, until, level="ad", conversion_goal=conversion_goal,
        )
        names_and_cpa = {e["entity_id"]: (e["entity_name"], e["cpa"]) for e in summary["entities"]}

        rows_by_currency: dict = {}
        for row in daily_rows:
            rows_by_currency.setdefault(row["currency"], []).append(row)

        all_cards: list[dict] = []
        cards_by_currency: dict[str, list[dict]] = {}
        for currency, rows in sorted(rows_by_currency.items()):
            rows_by_ad: dict = {}
            for row in rows:
                rows_by_ad.setdefault(row["entity_id"], []).append(row)
            ranked = _rank_cards(rows_by_ad, names_and_cpa)
            for card in ranked:
                card["verdict"] = _verdict(card, breakeven_value)
            cards_by_currency[currency] = ranked
            all_cards.extend(ranked)

        existing_by_id = schedule_repo.imported_ads_for_brand(conn, org_id, brand_id)
        _attach_creative(conn, org_id, brand_id, all_cards, existing_by_id)

        for currency, ranked in cards_by_currency.items():
            cards = [
                _card_view(card, existing_by_id.get(card["external_id"])) for card in ranked
            ]
            currencies.append({"currency": currency, "cards": cards})

    return {
        "connected": True, "backfill": backfill, "breakeven": breakeven,
        "currencies": currencies, "coordinates": coordinates,
    }


def tag_imported_ad(conn, org_id: str, brand_id: str, external_id: str, *,
                     keys: dict, owner_note: str | None, actor: str) -> dict:
    """票 past-ads/03：owner 自己標的七維座標＋一句話——`keys` 的每個非 None 值都得是
    *這個品牌、這個維度*、沒被停用的座標（`ValueError("coordinate_unknown:<dimension>")`
    否則），列本身必須已經被 GET 建過（`ValueError("imported_ad_unknown")` 否則，ADR 0067
    §1.2：GET 才是 imported_ad 的第一個寫入路徑，PUT 只改既有列）。不是版本化的欄位——
    ADR 0067 rule 2：「owner retagging their own memory overwrites it」，`audit_log` 留
    before。"""
    valid_by_dimension_key: dict[tuple[str, str], dict] = {
        (c["dimension"], c["key"]): c
        for c in schedule_repo.list_coordinates(conn, org_id, brand_id) if c["disabled_at"] is None
    }
    for dimension in COORDINATE_KEYS:
        key = keys.get(dimension)
        if key is not None and (dimension, key) not in valid_by_dimension_key:
            raise ValueError(f"coordinate_unknown:{dimension}")

    existing = schedule_repo.imported_ads_for_brand(conn, org_id, brand_id).get(external_id)
    if existing is None:
        raise ValueError("imported_ad_unknown")

    any_key_set = any(keys.get(dimension) is not None for dimension in COORDINATE_KEYS)
    status = "tagged" if any_key_set else "pending"
    updated = schedule_repo.update_imported_ad_tags(
        conn, org_id, brand_id, external_id, keys=keys, owner_note=owner_note or None,
        status=status, actor=actor,
    )
    write_audit(
        conn, org_id=org_id, brand_id=brand_id, entity_type="imported_ad", entity_id=existing["id"],
        action="tag", actor=actor, before=existing, after=updated,
    )
    conn.commit()
    return _tag_view(updated)


def imported_ad_count(conn, org_id: str, brand_id: str) -> int:
    return schedule_repo.count_imported_ads(conn, org_id, brand_id)
