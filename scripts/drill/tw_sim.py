"""scripts/drill/tw_sim.py — Taiwan Meta delivery simulator for drill 6 (2026-09-26).

A program, not a model: it takes a plan in the drill-6 contract (docs/drills/drill-6/contract.md),
an optional judge file (fit / context tags / compliance per ad, written by an LLM judge against
docs/drills/drill-6/judge-rubric.md), and a calendar, and emits one row per ad per day. Every
number is invented from the tables below; the only thing the LLM contributes is a bounded
multiplier and tags. Same rules for both sides, seeded by (side, period, ad name), so a rerun
gives the same rows.

    python -m scripts.drill.tw_sim run plan.json --judge fit.json --out rows.json [--prior prior_rows.json ...]
        [--audience group]   # drills 7-10 figure (group under its first ad's audience)
    python -m scripts.drill.tw_sim report rows.json            # markdown summary

These numbers say nothing about what real Meta would do. They rank two plans under one set of
assumptions, no more (docs/drills/README.md "The Meta stand-in").
"""

import argparse
import json
import math
import random
from collections import defaultdict
from datetime import date, timedelta

# --- assumptions (TW, e-commerce supplement, NT$; written down so they can be argued with) ---
BASE_CPM = 180.0          # NT$ per 1000 impressions
BASE_CTR = 0.012          # link clicks / impressions
BASE_CVR = 0.018          # purchases / clicks
DEFAULT_PRICE = 999.0

# cpm, ctr, cvr multipliers, daily spend cap (None = uncapped) for a brand with no pixel history
AUDIENCE = {
    "cold_unaware":       (0.85, 0.80, 0.50, None),
    "cold_problem_aware": (1.00, 1.00, 1.00, None),
    "warm_engaged":       (1.30, 1.60, 2.20, 300.0),
    "customer_repeat":    (1.20, 1.80, 3.00, 150.0),
    "lapsed":             (1.20, 1.20, 1.50, 100.0),
}
FORMAT = {"single_image": (1.00, 1.00), "carousel": (1.05, 1.05), "video": (0.95, 1.15)}  # cpm, ctr
OFFER_CVR = {"none": 1.0, "discount": 1.25, "bundle": 1.15, "free_shipping": 1.20,
             "trial_sample": 1.60, "guarantee": 1.10, "limited_time": 1.30}
PROOF_CVR = {"none": 1.0, "customer_review": 1.15, "expert_endorsement": 1.15, "lab_report": 1.10,
             "sales_numbers": 1.10, "media_coverage": 1.10, "founder_voice": 1.05}
FATIGUE_PER_DAY = {"single_image": 0.020, "carousel": 0.015, "video": 0.015}
# calendar: day -> (cpm, ctr, cvr, {context tag: ctr boost})
HOLIDAY = (1.25, 0.90, 0.85)
PRE_EXAM = {"student": 1.10}
EXAM = {"student": 1.25}
CALENDAR: dict = {}
for _d in ("2026-09-26", "2026-09-27"):           # 中秋連假尾
    CALENDAR[_d] = (*HOLIDAY, {"driver": 1.15})
CALENDAR["2026-09-28"] = (1.15, 0.95, 0.90, {})   # 教師節（週一放假）
for _d in ("2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02"):  # 收假上班上課
    CALENDAR[_d] = (1.00, 1.00, 1.05, {"worker": 1.05})
for _d in ("2026-10-03", "2026-10-04"):
    CALENDAR[_d] = (1.05, 0.95, 0.95, {})
for _d in ("2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"):  # 期中考前兩週
    CALENDAR[_d] = (1.00, 1.00, 1.00, PRE_EXAM)
for _d in ("2026-10-09", "2026-10-10", "2026-10-11"):                 # 國慶連假
    CALENDAR[_d] = (1.20, 0.90, 0.85, {"driver": 1.15})
for _d in ("2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"):  # 期中考週
    CALENDAR[_d] = (1.00, 1.00, 1.10, EXAM)
CALENDAR_DEFAULT = (1.0, 1.0, 1.0, {})


def _rng(*parts) -> random.Random:
    return random.Random("|".join(str(p) for p in parts))


def _pixel_factor(prior_purchases: int) -> float:
    if prior_purchases >= 100:
        return 1.05
    if prior_purchases >= 50:
        return 1.00
    return 0.90  # learning phase


def simulate(plan: dict, judge: dict | None = None, prior_rows: list | None = None,
             audience: str = "ad") -> list:
    """`audience="ad"` (default since drill 11): every ad is simulated under its own
    `audience_key` (falling back to its group's). `audience="group"` reproduces drills 7–10, where
    the whole group ran under the group key — which `export_plan` set to the FIRST ad's key — so
    drill 10's figures can be recomputed beside the per-ad ones."""
    judge = judge or {}
    prior_rows = prior_rows or []
    side, period = plan["side"], plan["period"]
    start, end = date.fromisoformat(plan["start_date"]), date.fromisoformat(plan["end_date"])
    days = [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    prior_purchases = sum(int(r["purchases"]) for r in prior_rows)
    prior_days_by_ad: dict = defaultdict(int)
    for r in prior_rows:
        prior_days_by_ad[r["ad_name"]] += 1
    pixel = _pixel_factor(prior_purchases)
    prior_clicks = sum(int(r["clicks"]) for r in prior_rows)
    # A retargetable pool is built by earlier delivery. No history ⇒ no pool ⇒ Meta delivers
    # nothing ("受眾太小"). Each prior click funds ~NT$2/day of warm reach; each prior purchase
    # ~NT$5/day of customer reach (stated assumptions, same for both sides).
    pool_cap = {"warm_engaged": min(300.0, prior_clicks * 2.0),
                "customer_repeat": min(150.0, prior_purchases * 5.0),
                "lapsed": 100.0 if prior_purchases >= 50 else 0.0}
    rows = []
    for group in plan["groups"]:
        ads = group.get("ads") or []
        if not ads:
            continue
        def key_of(ad, group=group):
            if audience == "group":
                return group.get("audience_key")
            return ad.get("audience_key") or group.get("audience_key")

        group_budget = float(group.get("daily_budget") or 0)
        for ad in ads:
            aud = key_of(ad)
            a_cpm, a_ctr, a_cvr, cap = AUDIENCE.get(aud or "cold_problem_aware",
                                                    AUDIENCE["cold_problem_aware"])
            # The pool is shared by the group's ads that target it (group mode: all of them).
            sharing = sum(1 for other in ads if key_of(other) == aud)
            j = judge.get(ad["name"], {})
            fit = min(1.4, max(0.6, float(j.get("fit", 1.0))))
            tags = set(j.get("tags") or [])
            compliance = j.get("compliance", "ok")
            fmt = ad.get("format_key") or "single_image"
            f_cpm, f_ctr = FORMAT.get(fmt, FORMAT["single_image"])
            price = float(ad.get("price") or DEFAULT_PRICE)
            if (ad.get("offer_key") == "trial_sample") and price > 200:
                price = 100.0  # a trial offer sells the trial SKU, whatever the ad row says
            budget = float(ad.get("daily_budget") or group_budget / len(ads))
            if cap is not None:
                budget = min(budget, pool_cap.get(aud, cap) / sharing)
            rng = _rng(side, period, ad["name"])
            fatigue_start = prior_days_by_ad.get(ad["name"], 0)
            for k, day in enumerate(days):
                c_cpm, c_ctr, c_cvr, boosts = CALENDAR.get(day, CALENDAR_DEFAULT)
                if compliance == "reject" or (compliance == "review" and k < 2):
                    rows.append(_row(side, period, group, ad, day, 0.0, 0, 0, 0, price))
                    continue
                pacing = 0.92 + 0.08 * rng.random()
                spend = round(budget * pacing, 2)
                cpm = BASE_CPM * a_cpm * f_cpm * c_cpm * (1 + 0.15 * max(0.0, budget - 1000) / 1000)
                impressions = int(spend / cpm * 1000)
                fatigue = max(0.5, 1 - FATIGUE_PER_DAY.get(fmt, 0.02) * (fatigue_start + k))
                tag_boost = max([boosts.get(t, 1.0) for t in tags] + [1.0])
                ctr = (BASE_CTR * a_ctr * f_ctr * c_ctr * math.sqrt(fit) * fatigue * tag_boost
                       * rng.gauss(1.0, 0.10))
                clicks = _poisson(rng, impressions * max(0.0, ctr))  # not int(): small budgets truncate to 0
                cvr = (BASE_CVR * a_cvr * c_cvr * math.sqrt(fit) * pixel
                       * OFFER_CVR.get(ad.get("offer_key") or "none", 1.0)
                       * (PROOF_CVR.get(ad.get("proof_key") or "none", 1.0)
                          if j.get("proof_present", True) else 1.0)  # a proof key with no proof in the copy is a label, not proof
                       * (boosts.get("student", 1.0) if "student" in tags else 1.0)
                       * rng.gauss(1.0, 0.20))
                purchases = _poisson(rng, clicks * max(0.0, cvr))
                rows.append(_row(side, period, group, ad, day, spend, impressions, clicks,
                                 purchases, price))
    return rows


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _row(side, period, group, ad, day, spend, impressions, clicks, purchases, price) -> dict:
    revenue = round(purchases * price, 2)
    return {"side": side, "period": period, "date": day, "group_name": group["name"],
            "ad_name": ad["name"], "spend": spend, "impressions": impressions, "clicks": clicks,
            "purchases": purchases, "revenue": revenue,
            "roas": round(revenue / spend, 2) if spend else None}


def report(rows: list) -> str:
    def agg(keyfn):
        out: dict = defaultdict(lambda: [0.0, 0, 0, 0, 0.0])
        for r in rows:
            a = out[keyfn(r)]
            a[0] += r["spend"]
            a[1] += r["impressions"]
            a[2] += r["clicks"]
            a[3] += r["purchases"]
            a[4] += r["revenue"]
        return out

    def line(name, a):
        spend, imp, clicks, buys, rev = a
        ctr = f"{clicks / imp * 100:.2f}%" if imp else "-"
        cvr = f"{buys / clicks * 100:.2f}%" if clicks else "-"
        cpa = f"{spend / buys:,.0f}" if buys else "-"
        roas = f"{rev / spend:.2f}" if spend else "-"
        return f"| {name} | {spend:,.0f} | {imp:,} | {ctr} | {buys} | {cvr} | {cpa} | {roas} |"

    head = "| | 花費 | 曝光 | CTR | 購買 | CVR | CPA | ROAS |\n|---|---|---|---|---|---|---|---|"
    parts = [head] + [line(k, v) for k, v in agg(lambda r: "總計").items()]
    parts += ["", "**受眾組**", head] + [line(k, v) for k, v in agg(lambda r: r["group_name"]).items()]
    parts += ["", "**廣告**", head] + [line(k, v) for k, v in agg(lambda r: r["ad_name"]).items()]
    parts += ["", "**逐日**", head] + [line(k, v) for k, v in sorted(agg(lambda r: r["date"]).items())]
    return "\n".join(parts)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="python -m scripts.drill.tw_sim")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("plan")
    p_run.add_argument("--judge")
    p_run.add_argument("--out", required=True)
    p_run.add_argument("--prior", nargs="*", default=[])
    p_run.add_argument("--start", help="override plan start_date (period window)")
    p_run.add_argument("--end", help="override plan end_date (period window)")
    p_run.add_argument("--audience", choices=("ad", "group"), default="ad",
                       help="ad: each ad under its own audience_key; group: drills 7-10 "
                            "(whole group under the group key = first ad's), for comparison")
    p_rep = sub.add_parser("report")
    p_rep.add_argument("rows")
    args = ap.parse_args()
    if args.cmd == "run":
        with open(args.plan, encoding="utf-8") as f:
            plan = json.load(f)
        judge = {}
        if args.judge:
            with open(args.judge, encoding="utf-8") as f:
                judge = json.load(f).get("ads", {})
        prior = []
        for p in args.prior:
            with open(p, encoding="utf-8") as f:
                prior += json.load(f)
        if args.start:
            plan["start_date"] = args.start
        if args.end:
            plan["end_date"] = args.end
        rows = simulate(plan, judge, prior, args.audience)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
        mode = "每則自己的" if args.audience == "ad" else "整組（演練 7–10 算法）"
        print(f"{plan['side']} 第 {plan['period']} 期：{len(rows)} 列（受眾＝{mode}）")
        print(report(rows))
    else:
        with open(args.rows, encoding="utf-8") as f:
            print(report(json.load(f)))
