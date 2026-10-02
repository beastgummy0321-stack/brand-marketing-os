"""scripts/drill/export_plan.py — read a brand's campaign out of the DB into the drill-6 contract.

The operator runs this on the persona's approved campaign so the simulator sees exactly what
the product built (coordinates, budgets, copy); the persona never hand-copies anything.

    python -m scripts.drill.export_plan <brand_id> --period N --out plan_B_N.json [--campaign <id>]
"""

import argparse
import json


def export(brand_id: str, period: int, campaign_id: str | None) -> dict:
    import app.main  # noqa: F401 — .env + assembly
    from app.core.db import connection

    with connection() as conn:
        if campaign_id:
            campaign = conn.execute("SELECT * FROM ads_campaign WHERE id = %s", (campaign_id,)).fetchone()
        else:
            campaign = conn.execute(
                "SELECT * FROM ads_campaign WHERE brand_id = %s ORDER BY created_at DESC LIMIT 1",
                (brand_id,)).fetchone()
        if campaign is None:
            raise SystemExit(f"品牌 {brand_id} 沒有 campaign")
        prices = {r["product_id"]: float(r["selling_price"]) for r in conn.execute(
            "SELECT product_id, selling_price FROM product_economics WHERE brand_id = %s"
            " AND selling_price IS NOT NULL ORDER BY effective_from", (brand_id,)).fetchall()}
        names = {r["id"]: r["name"] for r in conn.execute(
            "SELECT id, name FROM product WHERE brand_id = %s", (brand_id,)).fetchall()}
        # F45: each ad names its own customer group (who); the judge reads it per ad.
        who = {r["id"]: r["who"] for r in conn.execute(
            "SELECT id, who FROM product_customer_group WHERE brand_id = %s",
            (brand_id,)).fetchall()}
        ctx = campaign["context_json"] or {}
        campaign_product = (ctx.get("product_ids") or [None])[0]
        groups = []
        for g in conn.execute(
                "SELECT * FROM ads_delivery_group WHERE campaign_id = %s ORDER BY created_at",
                (campaign["id"],)).fetchall():
            ads = []
            # Group key = first ad's: only `tw_sim --audience group` reads it (drills 7-10's
            # figures); the default simulates every ad under its own `audience_key` below.
            audience_key = None
            for a in conn.execute("SELECT * FROM ads_ad WHERE group_id = %s ORDER BY created_at",
                                  (g["id"],)).fetchall():
                audience_key = audience_key or a["audience_key"]
                copy = {}
                if a["material_placement_id"]:
                    p = conn.execute("SELECT copy_fields FROM ads_asset_placement WHERE id = %s AND is_current",
                                     (a["material_placement_id"],)).fetchone()
                    copy = (p and p["copy_fields"]) or {}
                live = a["live_creative_json"] or {}
                ads.append({
                    "name": a["name"], "format_key": a["format_key"], "hook_key": a["hook_key"],
                    "pain_key": a["pain_key"], "angle_key": a["angle_key"],
                    "proof_key": a["proof_key"], "offer_key": a["offer_key"],
                    "audience_key": a["audience_key"],
                    "customer_group": who.get(a["customer_group_id"]),
                    # ads_ad.product_id was NULL for every ad in drill 6; fall back to the
                    # campaign's own product so the simulator prices purchases at the SKU sold
                    "product": names.get(a["product_id"] or campaign_product),
                    "price": prices.get(a["product_id"] or campaign_product),
                    "headline": copy.get("headline") or live.get("headline"),
                    "body": copy.get("body") or live.get("body"),
                    "asset_ready_source": a["asset_ready_source"],
                })
            groups.append({"name": g["name"], "role": g["role"], "channel": g["channel_key"],
                           "audience_key": audience_key, "audience_desc": None, "placement": None,
                           "daily_budget": float(g["daily_budget"] or 0), "ads": ads})
        num = lambda v: float(v) if v is not None else None  # noqa: E731
        return {
            "side": "B", "period": period, "campaign_id": campaign["id"], "name": campaign["name"],
            "start_date": str(campaign["start_date"]), "end_date": str(campaign["end_date"]),
            "objective": campaign["objective"], "success_metric": campaign["success_metric"],
            "success_target": num(campaign["success_target"]),
            "result_kind": campaign["result_kind"], "status": campaign["status"],
            "budget_planned": num(campaign["budget_planned"]),
            "daily_budget_total": sum(g["daily_budget"] for g in groups),
            "goal_text": campaign["goal_text"], "groups": groups,
            "kpi": {}, "hypothesis": None,
            "notes": "exported from MarketingOS by scripts/drill/export_plan.py",
        }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="python -m scripts.drill.export_plan")
    ap.add_argument("brand_id")
    ap.add_argument("--period", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--campaign")
    args = ap.parse_args()
    plan = export(args.brand_id, args.period, args.campaign)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1, default=str)
    n_ads = sum(len(g["ads"]) for g in plan["groups"])
    print(f"匯出 {plan['name']}：{len(plan['groups'])} 組、{n_ads} 則 → {args.out}")
