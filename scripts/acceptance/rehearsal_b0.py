# -*- coding: utf-8 -*-
"""scripts/acceptance/rehearsal_b0.py — engineer back door for rehearsal B0 (browser-only walk).

TEST TOOL, not a feature. Nothing under app/ or frontend/ is touched. Reuses the
CSV/row helpers of dryrun_a.py; every cycle it creates carries the [REHEARSAL-B0] mark so
the [ACCEPTANCE-A] cycles from the previous round are never touched.

Commands (all default to data/app.db; `build` backs the DB up first):
  build                       C1 (real history, 7 days) + C2 (planted problems, 14 days)
  build-c4                    C4 (whole cycle below stop-loss; late orders flip it)
  backdate --cycle ID --start YYYY-MM-DD
                              move a UI-created cycle (C3/C5) back in time, keeping its length
  csv --cycle ID --scenario decline [--winner AD_NAME]
                              C3 CSV: winner strong in week 1; from day 8 CTR 2.8%->1.0%,
                              CVR 2.6%->1.2%, frequency 1.6->4.4 (ROAS ~7.9 -> ~1.1 by day 14). Reads the cycle's publishing packages for ad names.
  authorize --cycle ID        back door for the "fill in Meta IDs" wall: map every package of
                              the cycle with placeholder IDs (go_live=False, nothing launched)
  purge                       drop every [REHEARSAL-B0] cycle (re-run of the rehearsal)

Timeline (today = 2026-08-24, real brand data exists from 2026-07-14):
  C1 2026-07-14..07-20 real  |  C2 07-21..08-03 planted  |  C3 08-04..08-17 (UI, backdated)
  C4 08-18..08-24 losing     |  C5 opened by the user from C4, stop at the proposal
"""

import argparse
import os
import shutil
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dryrun_a as A  # noqa: E402  (stdlib-only at import time)

REPO_ROOT = A.REPO_ROOT
BRAND_ID, PRODUCT_ID, AOV = A.BRAND_ID, A.PRODUCT_ID, A.AOV
MARK = "[REHEARSAL-B0]"
ACTOR = "rehearsal-b0"
OUT_DIR = REPO_ROOT / ".scratch" / "orchestrator" / "rehearsal-B0" / "csv"

C1_START, C1_DAYS = date(2026, 7, 14), 7
C2_START, C2_DAYS, C2_BUDGET = date(2026, 7, 21), 14, 30000
C4_START, C4_DAYS, C4_BUDGET = date(2026, 8, 18), 7, 35000
BASE_CPM, BASE_CTR, BASE_CVR = 91.0, 0.0269, 0.02255  # this brand's real-ish medians

# C2 planted problems: one loses money (限時優惠), one fatigues (健身教練推薦), CPM doubles
# for everyone from day 8 (same spend, half the impressions -> half the clicks/orders).
C2_ADS = {
    "實證成分":   dict(spend=4500.0, ctr=BASE_CTR, cvr=BASE_CVR, freq=(1.8, 1.8)),
    "使用者見證": dict(spend=4500.0, ctr=BASE_CTR, cvr=BASE_CVR, freq=(1.8, 1.8)),
    "成分對比":   dict(spend=4500.0, ctr=BASE_CTR, cvr=BASE_CVR, freq=(1.8, 1.8)),
    "健身教練推薦": dict(spend=4500.0, ctr=BASE_CTR, cvr=BASE_CVR, freq=(1.8, 4.5),
                     ctr_w2=(0.024, 0.015)),
    "限時優惠":   dict(spend=12000.0, ctr=0.00758, cvr=0.016, freq=(1.8, 1.8)),
}
# C4: everything below the stop-loss line (breakeven 1.42 x 0.7 = 0.99). CPA 1000 -> ROAS 0.86.
C4_ADS = {
    "節慶禮盒":  dict(spend=12000.0, ctr=0.015, cvr=0.008, freq=(1.6, 2.2)),
    "買二送一":  dict(spend=12000.0, ctr=0.015, cvr=0.008, freq=(1.6, 2.2)),
    "名人代言":  dict(spend=11000.0, ctr=0.015, cvr=0.008, freq=(1.6, 2.2)),
}
C4_CPM = 120.0
C4_LATE_REVENUE = 25000.0  # pulls ROAS 0.86 -> ~1.57 (above breakeven 1.42, below scale line 1.85)


def _lerp(a, b, i, n):
    return a if n <= 1 else a + (b - a) * i / (n - 1)


def _series(start, n_days, ads, names, cpm, *, cpm_x2_from=None):
    """Daily rows per ad. spend evenly split; impressions from CPM; clicks from CTR; orders
    from CVR; revenue = orders x AOV. Returns list of (day_idx, row)."""
    out = []
    for angle, spec in ads.items():
        nm = names[angle]
        for i in range(n_days):
            d = start + timedelta(days=i)
            day_idx = i + 1
            spend = spec["spend"] / n_days
            day_cpm = cpm * (2 if cpm_x2_from and day_idx >= cpm_x2_from else 1)
            impressions = spend / day_cpm * 1000
            ctr = spec["ctr"]
            if "ctr_w2" in spec and day_idx >= 8:
                ctr = _lerp(spec["ctr_w2"][0], spec["ctr_w2"][1], day_idx - 8, n_days - 7)
            clicks = impressions * ctr
            cvr = spec["cvr"]
            if "cvr_w2" in spec and day_idx >= 8:
                cvr = _lerp(spec["cvr_w2"][0], spec["cvr_w2"][1], day_idx - 8, n_days - 7)
            orders = clicks * cvr
            freq = round(_lerp(spec["freq"][0], spec["freq"][1], i, n_days), 2)
            out.append((day_idx, A._row(nm["campaign_name"], nm["ad_name"], d.isoformat(),
                                        impressions, clicks, spend, orders, orders * AOV,
                                        freq, impressions / freq)))
    return out


def _late_rows(start, n_days, ads, names, revenue_by_angle):
    d = (start + timedelta(days=n_days - 1)).isoformat()
    rows = []
    for angle in ads:
        nm = names[angle]
        rev = revenue_by_angle[angle]
        rows.append(A._row(nm["campaign_name"], nm["ad_name"], d, 0, 0, 0, rev / AOV, rev,
                           ads[angle]["freq"][1], 0))
    return rows


def _make_packages(conn, cycle, angles, tag):
    """experiment_cell + publishing_package + external_ad_mapping per angle — same raw-insert
    precedent as dryrun_a._build_cycle1 (no public creator short of the full LLM plan flow)."""
    from app.ads import handoff
    from app.brand_intelligence import repository as bi
    from app.core.db import new_id, now_iso

    brand = bi.get_brand(conn, BRAND_ID)
    names = {}
    for i, angle in enumerate(angles, start=1):
        ts = now_iso()
        cell_id = new_id("exc")
        conn.execute(
            "INSERT INTO experiment_cell (id, campaign_cycle_id, brand_id, product_id, audience,"
            " creative_angle, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cell_id, cycle["id"], BRAND_ID, PRODUCT_ID, "冷受眾：健身／增肌興趣 25-40", angle, ts))
        nm = handoff.build_names(brand, cycle, {"id": cell_id, "creative_angle": angle}, index=i)
        pkg_id = new_id("pkg")
        conn.execute(
            "INSERT INTO publishing_package (id, brand_id, campaign_cycle_id,"
            " experiment_cell_id, product_id, campaign_name, adset_name, ad_name,"
            " destination_url, utm_json, objective, daily_budget, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?, 'ready', ?)",
            (pkg_id, BRAND_ID, cycle["id"], cell_id, PRODUCT_ID, nm["campaign_name"],
             nm["adset_name"], nm["ad_name"], "https://beastprime.example/beast-gummy",
             cycle["objective"], round(angles[angle]["spend"] / cycle_days(cycle), 2), ts))
        conn.commit()
        handoff.authorize_and_map(
            conn, BRAND_ID, cycle["id"], pkg_id,
            meta_ids={"meta_campaign_id": f"{tag}-{i:02d}"}, actor=ACTOR, go_live=False)
        names[angle] = nm
    return names


def cycle_days(cycle):
    return (date.fromisoformat(cycle["end_date"]) - date.fromisoformat(cycle["start_date"])).days + 1


def _attach_hypothesis(conn, cycle_id, statement):
    from app.brand_intelligence import repository as bi

    hyp = bi.create_strategy_hypothesis(
        conn, BRAND_ID, hypothesis_type="message", statement=statement, created_by=ACTOR,
        actor=ACTOR, product_id=PRODUCT_ID, source_cycle_id=cycle_id)
    conn.execute(
        "INSERT OR IGNORE INTO campaign_cycle_hypothesis (campaign_cycle_id,"
        " strategy_hypothesis_id, brand_id, role) VALUES (?, ?, ?, 'message')",
        (cycle_id, hyp["id"], BRAND_ID))
    conn.commit()
    return hyp


def _new_cycle(conn, start, days, budget, background):
    from app.ads import repository as ads_repo

    cycle = ads_repo.create_cycle(
        conn, BRAND_ID, product_ids=[PRODUCT_ID], pain_value=budget, objective="sales",
        actor=ACTOR, start_date=start.isoformat(), duration_days=days,
        background=f"{MARK} {background}")
    ads_repo.update_cycle_status(conn, BRAND_ID, cycle["id"], status="LIVE", actor=ACTOR)
    return cycle


# ---------------------------------------------------------------------------
# C1 — real history
# ---------------------------------------------------------------------------

def _build_c1(conn):
    start_s = C1_START.isoformat()
    end_s = (C1_START + timedelta(days=C1_DAYS - 1)).isoformat()
    rows = A._cycle0_rows(conn, start_s, end_s)
    if not rows:
        raise RuntimeError(f"沒有 {start_s}..{end_s} 的品牌層真實資料")
    spend_total = sum(r["spend"] or 0 for r in rows)
    budget = int(round(spend_total / 1000.0 + 0.5)) * 1000
    cycle = _new_cycle(conn, C1_START, C1_DAYS, budget, "C1 真歷史基準")
    csv_rows = [
        (r["campaign_name"] or r["meta_campaign_id"], r["meta_ad_id"], r["d"], r["d"],
         r["impressions"] or 0, r["clicks"] or 0, r["spend"] or 0, r["conversions"] or 0,
         r["revenue"] or 0, r["frequency"], r["reach"] or 0)
        for r in rows
    ]
    return cycle, {"C1_real_7days.csv": A._csv_text(csv_rows)}


# ---------------------------------------------------------------------------
# C2 — planted problems
# ---------------------------------------------------------------------------

def _build_c2(conn):
    cycle = _new_cycle(conn, C2_START, C2_DAYS, C2_BUDGET, "C2 埋題")
    names = _make_packages(conn, cycle, C2_ADS, "rehearsal-b0-c2")
    _attach_hypothesis(conn, cycle["id"], "拿證據說話的切角（實證成分／成分對比）比純促銷更能拉高轉換率")
    rows = _series(C2_START, C2_DAYS, C2_ADS, names, BASE_CPM, cpm_x2_from=8)
    w1 = [r for d, r in rows if d <= 7]
    w2 = [r for d, r in rows if d >= 8]
    revenue = {a: sum(r[8] for d, r in rows if r[1] == names[a]["ad_name"]) for a in C2_ADS}
    late = _late_rows(C2_START, C2_DAYS, C2_ADS, names, {a: round(v * 0.15, 2) for a, v in revenue.items()})
    return cycle, {
        "C2_week1_days1-7.csv": A._csv_text(w1),
        "C2_week2_days8-14.csv": A._csv_text(w2),
        "C2_late_orders.csv": A._csv_text(late),
    }


# ---------------------------------------------------------------------------
# C4 — whole cycle losing, late orders flip it
# ---------------------------------------------------------------------------

def _build_c4(conn):
    cycle = _new_cycle(conn, C4_START, C4_DAYS, C4_BUDGET, "C4 整期賠錢")
    names = _make_packages(conn, cycle, C4_ADS, "rehearsal-b0-c4")
    _attach_hypothesis(conn, cycle["id"], "節慶檔期用禮盒／組合切角能拉高客單價，投報率會比平常好")
    rows = [r for _, r in _series(C4_START, C4_DAYS, C4_ADS, names, C4_CPM)]
    share = {a: s["spend"] / C4_BUDGET for a, s in C4_ADS.items()}
    late = _late_rows(C4_START, C4_DAYS, C4_ADS, names,
                      {a: round(C4_LATE_REVENUE * share[a], 2) for a in C4_ADS})
    return cycle, {"C4_full_7days.csv": A._csv_text(rows), "C4_late_orders.csv": A._csv_text(late)}


# ---------------------------------------------------------------------------
# C3 — CSV for a cycle the user opened through the front door
# ---------------------------------------------------------------------------

def _csv_decline(conn, cycle_id, winner):
    from app.ads import repository as ads_repo

    cycle = ads_repo.get_cycle(conn, BRAND_ID, cycle_id)
    pkgs = conn.execute(
        "SELECT ad_name, campaign_name, daily_budget FROM publishing_package"
        " WHERE brand_id = ? AND campaign_cycle_id = ? ORDER BY created_at", (BRAND_ID, cycle_id),
    ).fetchall()
    if not pkgs:
        raise RuntimeError("這期沒有交接包（publishing_package）——正門還沒走到素材／交接包那步")
    n = cycle_days(cycle)
    start = date.fromisoformat(cycle["start_date"])
    win_name = winner or pkgs[0]["ad_name"]
    if not any(p["ad_name"] == win_name for p in pkgs):
        raise RuntimeError(f"找不到廣告 {win_name!r}；這期有：{[p['ad_name'] for p in pkgs]}")
    budgets = [p["daily_budget"] or (cycle["budget"] / n / len(pkgs)) for p in pkgs]
    ads, names = {}, {}
    for p, db in zip(pkgs, budgets):
        is_win = p["ad_name"] == win_name
        ads[p["ad_name"]] = dict(
            spend=db * n,
            ctr=0.032 if is_win else 0.022, cvr=0.026 if is_win else 0.019,
            freq=(1.6, 4.4) if is_win else (1.7, 1.9),
            **({"ctr_w2": (0.028, 0.010), "cvr_w2": (0.026, 0.012)} if is_win else {}))
        names[p["ad_name"]] = {"campaign_name": p["campaign_name"], "ad_name": p["ad_name"]}
    rows = _series(start, n, ads, names, BASE_CPM)
    w1 = [r for d, r in rows if d <= 7]
    w2 = [r for d, r in rows if d >= 8]
    tag = cycle_id[-4:]
    return {f"C3_{tag}_week1_days1-7.csv": A._csv_text(w1), f"C3_{tag}_week2_days8-{n}.csv": A._csv_text(w2)}


# ---------------------------------------------------------------------------
# plumbing
# ---------------------------------------------------------------------------

def _open(db_arg):
    os.environ["BRAND_OS_DB"] = str(Path(db_arg).resolve())
    import app.main as main  # noqa: E402
    return main.conn


def _backup(db_arg, conn):
    backup_dir = REPO_ROOT / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dst = backup_dir / f"app.pre-rehearsal-B0.{ts}.db"
    conn.commit()
    shutil.copy2(Path(db_arg).resolve(), dst)
    print(f"backup: {dst}")


def _write_csvs(csvs):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in csvs.items():
        (OUT_DIR / name).write_text(text, encoding="utf-8-sig")  # BOM: Meta exports carry one
        print(f"csv: {OUT_DIR / name}")


def _rehearsal_cycles(conn):
    from app.ads import repository as ads_repo
    # MARK can sit mid-string: front-door cycles (C3/C5) get it appended by `backdate`,
    # after the UI already wrote the direction choice into background.
    return [c for c in ads_repo.list_cycles(conn, BRAND_ID, include_archived=True)
            if MARK in (c.get("background") or "")]


def _print(cycle):
    print(f"{cycle['id']}  {cycle['start_date']}..{cycle['end_date']}  budget {cycle['budget']}  {cycle['background']}")


def cmd_build(db):
    conn = _open(db)
    # C4 may already exist: B2 builds C4 before C1/C2 to reproduce F1 (old cycle shadowed by newer).
    if any(("C1" in (c.get("background") or "")) or ("C2" in (c.get("background") or "")) for c in _rehearsal_cycles(conn)):
        print(f"refuse: 已有 {MARK} C1/C2 檔期，先 purge")
        return 1
    _backup(db, conn)
    c1, csv1 = _build_c1(conn)
    c2, csv2 = _build_c2(conn)
    _write_csvs({**csv1, **csv2})
    _print(c1); _print(c2)
    return 0


def cmd_build_c4(db):
    conn = _open(db)
    if any("C4" in (c.get("background") or "") for c in _rehearsal_cycles(conn)):
        print("refuse: C4 已存在")
        return 1
    _backup(db, conn)
    c4, csv4 = _build_c4(conn)
    _write_csvs(csv4)
    _print(c4)
    return 0


def cmd_backdate(db, cycle_id, start_s):
    conn = _open(db)
    from app.ads import repository as ads_repo
    from app.ads import occasion as ads_occasion

    cycle = ads_repo.get_cycle(conn, BRAND_ID, cycle_id)
    n = cycle_days(cycle)
    start = date.fromisoformat(start_s)
    end = start + timedelta(days=n - 1)
    _backup(db, conn)
    conn.execute(
        "UPDATE campaign_cycle SET start_date = ?, end_date = ?, occasion = ?,"
        " background = COALESCE(background || ' ', '') || ? WHERE id = ? AND brand_id = ?",
        (start.isoformat(), end.isoformat(), ads_occasion.for_cycle(start, end),
         f"{MARK} backdated from {cycle['start_date']}", cycle_id, BRAND_ID))
    conn.commit()
    _print(ads_repo.get_cycle(conn, BRAND_ID, cycle_id))
    return 0


def cmd_csv(db, cycle_id, scenario, winner):
    conn = _open(db)
    if scenario != "decline":
        print("only scenario 'decline' exists")
        return 1
    _write_csvs(_csv_decline(conn, cycle_id, winner))
    return 0


def cmd_authorize(db, cycle_id):
    conn = _open(db)
    from app.ads import handoff

    pkgs = conn.execute(
        "SELECT p.id, p.ad_name, (SELECT COUNT(*) FROM external_ad_mapping m"
        " WHERE m.publishing_package_id = p.id) mapped FROM publishing_package p"
        " WHERE p.brand_id = ? AND p.campaign_cycle_id = ? ORDER BY p.created_at",
        (BRAND_ID, cycle_id)).fetchall()
    if not pkgs:
        print("這期沒有交接包")
        return 1
    _backup(db, conn)
    for i, p in enumerate(pkgs, start=1):
        if p["mapped"]:
            print("already mapped:", p["ad_name"])
            continue
        handoff.authorize_and_map(
            conn, BRAND_ID, cycle_id, p["id"],
            meta_ids={"meta_campaign_id": f"rehearsal-b0-{cycle_id[-4:]}-{i:02d}"},
            actor=ACTOR, go_live=False)
        print("mapped:", p["ad_name"])
    from app.ads import repository as ads_repo
    cyc = ads_repo.get_cycle(conn, BRAND_ID, cycle_id)
    if cyc["status"] != "LIVE":
        ads_repo.update_cycle_status(conn, BRAND_ID, cycle_id, status="LIVE", actor=ACTOR)
        print("status ->", "LIVE")
    return 0


def cmd_purge(db, also=()):
    conn = _open(db)
    from app.ads import repository as ads_repo
    _backup(db, conn)
    extra = [ads_repo.get_cycle(conn, BRAND_ID, i) for i in also]
    for c in _rehearsal_cycles(conn) + [e for e in extra if e]:
        if not c["archived"]:
            ads_repo.set_cycle_archived(conn, BRAND_ID, c["id"], archived=True, actor=ACTOR)
        ads_repo.delete_cycle(conn, BRAND_ID, c["id"], actor=ACTOR)
        print("deleted", c["id"])
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=str(REPO_ROOT / "data" / "app.db"))
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("build"); sub.add_parser("build-c4")
    pg = sub.add_parser("purge"); pg.add_argument("--also", nargs="*", default=[])
    z = sub.add_parser("authorize"); z.add_argument("--cycle", required=True)
    b = sub.add_parser("backdate"); b.add_argument("--cycle", required=True); b.add_argument("--start", required=True)
    c = sub.add_parser("csv"); c.add_argument("--cycle", required=True)
    c.add_argument("--scenario", default="decline"); c.add_argument("--winner")
    a = p.parse_args()
    if a.command == "build":
        sys.exit(cmd_build(a.db))
    if a.command == "build-c4":
        sys.exit(cmd_build_c4(a.db))
    if a.command == "backdate":
        sys.exit(cmd_backdate(a.db, a.cycle, a.start))
    if a.command == "csv":
        sys.exit(cmd_csv(a.db, a.cycle, a.scenario, a.winner))
    if a.command == "purge":
        sys.exit(cmd_purge(a.db, a.also))
    if a.command == "authorize":
        sys.exit(cmd_authorize(a.db, a.cycle))


if __name__ == "__main__":
    main()
