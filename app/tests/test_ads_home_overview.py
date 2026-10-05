"""app/tests/test_ads_home_overview.py — F28-I06 "Home overview" falsifiers.

Invariants: one `spent` for the whole payload, quality buckets that sum to it exactly (spend not
on a graded active ad lands in `ungraded`), grades taken from `triage.classify` (never
recomputed), earn over purchase campaigns only, unknown as null (never zero, never a sum across
currencies), the previous month's same elapsed days, and one failing read nulling only its block.

Clock: every test pins "today" to 2026-09-23 through `app.core.settings.today_for_org` (the one
seam `month_summary._month_window` and `month_budget.view` read) and `db.now_utc` to noon of that
day (`_pinned`; the bound account `act_1`'s last complete day reads the instant, F50 Contract K),
except the timezone test, which pins the wall clock only so the org-timezone rule itself runs.
`triage.classify` is replaced by a stub that returns the grades a test chooses -- which is the
point: the home must show whatever triage graded, not re-grade from its own numbers.
"""

import contextlib
import unittest
from datetime import UTC, date, datetime, time, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

from app.ads import (
    change_control_launch,
    channels,
    handoff_assignment,
    home_overview,
    month_budget,
    repository,
    triage,
)
from app.ads import external_repository as external
from app.brand_intelligence import repository as bi_repo
from app.core import db
from app.core import settings as coresettings

TODAY = date(2026, 9, 23)
MONTH = "2026-09"


class _TaipeiAccount:
    """`act_1`, the fixtures' bound Meta account, in the org's zone (Asia/Taipei)."""

    def accounts(self, conn, org, brand):
        return [{"account_id": "act_1", "name": "主帳戶", "timezone_name": "Asia/Taipei"}]


def _bound_meta():
    """`act_1` is bound in Taipei, so the brand's last complete day (`coverage.last_complete_day`,
    F50 Contract K) is the account's yesterday -- not the fail-closed fallback."""
    real = channels.external_reader
    return mock.patch.object(
        channels, "external_reader",
        side_effect=lambda platform: _TaipeiAccount() if platform == "meta" else real(platform),
    )


@contextlib.contextmanager
def _pinned(day):
    """The clock at noon of `day` in Taipei: `today_for_org` and `db.now_utc` agree (the
    account's last complete day reads the instant, F50 Contract K)."""
    noon = datetime.combine(day, time(12), tzinfo=ZoneInfo("Asia/Taipei")).astimezone(UTC)
    with (
        mock.patch.object(coresettings, "today_for_org", return_value=day),
        mock.patch.object(db, "now_utc", return_value=noon),
    ):
        yield


def _brand(conn, org, name):
    brand = bi_repo.create_brand(conn, org_id=org, name=name, actor="test", client_name=None)
    conn.commit()
    return brand["id"]


def _product(conn, brand, *, unit_variable_cost):
    product_id = bi_repo.create_product(conn, brand, name="測試商品", actor="test")["id"]
    bi_repo.save_product_economics(
        conn, brand, product_id, selling_price=500, currency="TWD", confirmed_by="test",
        actor="test", unit_variable_cost=unit_variable_cost, shipping_cost=50,
    )
    conn.commit()
    return product_id  # break-even = 500 - cost - 50


def _imported(conn, org, brand, name, native_id, *, result_kind="purchase", cap=None,
              product_id=None):
    campaign_id = external.create_imported_campaign(conn, org, brand, name=name)["id"]
    external.upsert_entity(conn, org, brand, campaign_id, {
        "platform": "meta", "source_account": "act_1", "native_kind": "campaign",
        "native_id": native_id,
    })
    conn.commit()
    if result_kind is not None or cap is not None or product_id is not None:
        repository.save_campaign_target(
            conn, org, brand, campaign_id, result_kind=result_kind,
            basis="own" if cap is not None else None, value=cap, product_id=product_id,
            expected_revision=0, actor="test",
        )
    conn.commit()
    return campaign_id


def _ad(conn, org, brand, campaign_id, native_id, parent, *, status="ACTIVE"):
    entity = external.upsert_entity(conn, org, brand, campaign_id, {
        "platform": "meta", "source_account": "act_1", "native_kind": "ad",
        "native_id": native_id, "name": native_id, "native_status": status,
        "parent_native_kind": "campaign", "parent_native_id": parent,
    })
    conn.commit()
    return entity["id"]


def _obs(conn, org, brand, campaign_id, ad_id, day, *, spend, count=0, currency="TWD",
         kind="purchase", key="a"):
    external.upsert_observation(
        conn, org, brand, campaign_id,
        {"entity_id": ad_id, "day": day, "metric_scope": "ad", "attribution_key": key,
         "currency": currency, "source": "meta", "spend": spend, "impressions": 100,
         "purchases": None},
        result_kind=kind, result_count=count, result_action="omni_purchase",
        result_attribution="7d_click+1d_view",
    )
    conn.commit()


def _fake_classify(grades):
    """`triage.classify` stand-in: every ad id in `grades` becomes an active triage item with that
    grade, under whichever campaign asked."""

    def classify(conn, org_id, brand_id, campaign_id):
        rows = conn.execute(
            "SELECT id,name FROM ads_external_entity WHERE org_id=%s AND brand_id=%s "
            "AND campaign_id=%s AND native_kind='ad'",
            (org_id, brand_id, campaign_id),
        ).fetchall()
        items = [
            {"entity_id": r["id"], "name": r["name"], "thumbnail_url": None,
             "campaign_id": campaign_id, "grade": grades[r["id"]]}
            for r in rows if r["id"] in grades
        ]
        return {"items": items}

    return classify


class _Pinned(unittest.TestCase):
    """Pins today and triage for every test; `self.grades` feeds the triage stub."""

    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.grades = {}
        today = _pinned(TODAY)
        classify = mock.patch.object(triage, "classify", side_effect=self._classify)
        bound = _bound_meta()
        today.__enter__()
        classify.start()
        bound.start()
        self.addCleanup(today.__exit__, None, None, None)
        self.addCleanup(classify.stop)
        self.addCleanup(bound.stop)

    def _classify(self, *args):
        return _fake_classify(self.grades)(*args)

    def overview(self, brand, month=MONTH):
        return home_overview.get_overview(self.conn, self.org, brand, month)


class OneSpentTest(_Pinned):
    def setUp(self):
        super().setUp()
        conn, org = self.conn, self.org
        self.brand = brand = _brand(conn, org, "首頁總覽：一個已花")
        product = _product(conn, brand, unit_variable_cost=150)  # break-even 300
        self.buy = _imported(conn, org, brand, "日常轉換", "c_buy", cap=250, product_id=product)
        self.a1 = _ad(conn, org, brand, self.buy, "a1", "c_buy")
        self.a2 = _ad(conn, org, brand, self.buy, "a2", "c_buy")
        self.a3 = _ad(conn, org, brand, self.buy, "a3", "c_buy", status="PAUSED")
        self.lead = _imported(conn, org, brand, "名單活動", "c_lead", result_kind="lead")
        self.l1 = _ad(conn, org, brand, self.lead, "l1", "c_lead")
        self.old = _imported(conn, org, brand, "已結案活動", "c_old", cap=250, product_id=product)
        self.o1 = _ad(conn, org, brand, self.old, "o1", "c_old")
        conn.execute("UPDATE ads_campaign SET status='closed' WHERE id=%s", (self.old,))
        conn.commit()

        _obs(conn, org, brand, self.buy, self.a1, date(2026, 9, 1), spend=400, count=2)
        _obs(conn, org, brand, self.buy, self.a1, date(2026, 9, 22), spend=200, count=1)
        _obs(conn, org, brand, self.buy, self.a2, date(2026, 9, 10), spend=900, count=0)
        _obs(conn, org, brand, self.buy, self.a3, date(2026, 9, 5), spend=150, count=0)
        _obs(conn, org, brand, self.lead, self.l1, date(2026, 9, 12), spend=300, count=4,
             kind="lead")
        _obs(conn, org, brand, self.old, self.o1, date(2026, 9, 2), spend=50, count=0)
        # Outside the window: today (not complete) and last month.
        _obs(conn, org, brand, self.buy, self.a1, TODAY, spend=9999, count=9)
        _obs(conn, org, brand, self.buy, self.a1, date(2026, 8, 31), spend=7777, count=7)
        # a1 is cheap by its own numbers, but triage says 太貴 -- the home must say 太貴.
        self.grades = {self.a1: "over", self.a2: "wasted", self.l1: "insufficient"}

    def test_one_spent_and_buckets_sum_to_it(self):
        home = self.overview(self.brand)
        self.assertEqual(home["month"], MONTH)
        self.assertEqual(home["day_of_month"], 23)
        self.assertEqual(home["days_in_month"], 30)
        self.assertEqual(home["currency"], "TWD")
        self.assertEqual(home["spent"], 400 + 200 + 900 + 150 + 300 + 50)

        buckets = {b["grade"]: b for b in home["quality"]["buckets"]}
        self.assertEqual([b["grade"] for b in home["quality"]["buckets"]],
                         list(home_overview.BUCKET_ORDER))
        self.assertEqual(sum(b["amount"] for b in buckets.values()), home["spent"])
        self.assertEqual(buckets["over"]["amount"], 600)  # triage's grade, not recomputed
        self.assertEqual([a["entity_id"] for a in buckets["over"]["ads"]], [self.a1])
        self.assertEqual(buckets["wasted"]["amount"], 900)
        self.assertEqual(buckets["insufficient"]["amount"], 300)
        self.assertEqual(buckets["on_target"]["amount"], 0)
        # Closed ad (a3) and the closed campaign's ad (o1) are never graded.
        self.assertEqual(buckets["ungraded"]["amount"], 200)
        self.assertEqual(buckets["ungraded"]["count"], 2)
        self.assertEqual([a["entity_id"] for a in buckets["ungraded"]["ads"]],
                         [self.a3, self.o1])
        # F48: a graded ad carries its triage item's shown sample; an ungraded one has none.
        self.assertIn("sample", buckets["over"]["ads"][0])
        self.assertIsNone(buckets["ungraded"]["ads"][0]["sample"])

    def test_pace_daily_ends_at_spent(self):
        pace = self.overview(self.brand)["pace"]
        self.assertEqual(len(pace["daily"]), 22)  # 9/1 .. 9/22, today excluded
        self.assertEqual(pace["daily"][0], {"day": "2026-09-01", "cumulative": 400})
        self.assertEqual(pace["daily"][-1]["day"], "2026-09-22")
        self.assertEqual(pace["daily"][-1]["cumulative"], 2000)
        self.assertEqual(pace["projected_month_end"], round(2000 / 22 * 30, 2))
        # No monthly budget confirmed: nothing to compare against, never a zero.
        self.assertIsNone(pace["budget_amount"])
        self.assertIsNone(pace["available"])
        self.assertIsNone(pace["budget_to_date"])

    def test_money_is_purchase_campaigns_only(self):
        money = self.overview(self.brand)["money"]
        # buy: 1650 spend / 3 purchases; old (closed, purchase): 50 spend / 0 purchases.
        self.assertEqual(money["purchases"], 3)
        self.assertEqual(money["cost_per_purchase"], round(1700 / 3, 2))
        self.assertEqual(money["cap"], {"value": 250, "basis": "own", "break_even": 300})
        self.assertEqual(money["earn_after_cost_and_ads"], 3 * 300 - 1700)
        self.assertEqual(money["earn_missing"], [])
        self.assertEqual(money["excluded"], [
            {"campaign_id": self.lead, "name": "名單活動", "reason": "not_purchase"},
        ])

    def test_campaign_rows(self):
        home = self.overview(self.brand)
        ids = [c["campaign_id"] for c in home["campaigns"]]
        self.assertEqual(ids, [self.buy, self.lead])  # closed campaign absent, spend desc
        buy, lead = home["campaigns"]
        self.assertEqual(buy["month_spend"], 1650)
        self.assertEqual(buy["purchases"], 3)
        self.assertEqual(buy["cost_per_purchase"], 550)
        self.assertEqual(buy["cap"], {"value": 250, "basis": "own", "break_even": 300})
        self.assertEqual(buy["active_ads"], 2)
        self.assertIsNone(buy["draft"])
        self.assertEqual(buy["origin"], "imported")
        self.assertEqual(lead["month_spend"], 300)
        self.assertIsNone(lead["purchases"])  # not a purchase campaign
        self.assertIsNone(lead["cost_per_purchase"])
        self.assertIsNone(lead["cap"])  # a lead campaign has no break-even and no own cap

    def test_running_counts_only_running_ads_and_the_lifecycle_is_served(self):
        """F49 Contract L: 「在投」 is the running count; a disapproved ad is not running, an ad
        with no status is counted apart as unknown."""
        conn, org, brand = self.conn, self.org, self.brand
        _ad(conn, org, brand, self.buy, "a4", "c_buy", status="DISAPPROVED")
        _ad(conn, org, brand, self.buy, "a5", "c_buy", status=None)
        home = self.overview(brand)
        buy = next(c for c in home["campaigns"] if c["campaign_id"] == self.buy)
        self.assertEqual(buy["active_ads"], 2)
        self.assertEqual(buy["running"],
                         {"count": 2, "unknown": 1, "read_at": None, "stale": False})
        self.assertEqual(buy["lifecycle"],
                         {"state": "live", "label": "投放中", "can_close": False})

    def test_closed_this_month_counts_campaigns_closed_in_the_month(self):
        # N3: the closed campaign is gone from the rows, but the home knows one was closed.
        self.assertEqual(self.overview(self.brand)["closed_this_month"], 0)  # no closed_at
        self.conn.execute(
            "UPDATE ads_campaign SET closed_at=%s WHERE id=%s",
            (datetime(2026, 9, 10, 4, 0, tzinfo=UTC), self.old),
        )
        self.conn.commit()
        self.assertEqual(self.overview(self.brand)["closed_this_month"], 1)
        self.assertEqual(self.overview(self.brand, "2026-08")["closed_this_month"], 0)

    def test_previous_same_period_counts_the_same_elapsed_days(self):
        conn, org = self.conn, self.org
        _obs(conn, org, self.brand, self.buy, self.a1, date(2026, 8, 22), spend=300, count=3,
             key="p")
        _obs(conn, org, self.brand, self.buy, self.a1, date(2026, 8, 23), spend=5000, count=50,
             key="p")
        previous = self.overview(self.brand)["money"]["previous_same_period"]
        self.assertEqual(previous, {"days": 22, "purchases": 3, "cost_per_purchase": 100})

    def test_timeline_today_then_month_review(self):
        timeline = self.overview(self.brand)["timeline"]
        self.assertEqual(timeline[0], {"date": "2026-09-23", "kind": "today",
                                       "campaign_id": None, "name": None, "ready": None})
        self.assertEqual(timeline[1]["kind"], "month_review")
        self.assertEqual(timeline[1]["date"], "2026-09-30")

    def test_one_failing_read_nulls_only_its_block(self):
        with mock.patch.object(month_budget, "view", side_effect=RuntimeError("boom")):
            home = self.overview(self.brand)
        self.assertIsNone(home["pace"])
        self.assertEqual(home["spent"], 2000)
        self.assertIsNotNone(home["money"])
        self.assertIsNotNone(home["quality"])
        self.assertEqual(len(home["campaigns"]), 2)
        self.assertIsNotNone(home["sync"])

        with mock.patch.object(triage, "classify", side_effect=RuntimeError("boom")):
            home = self.overview(self.brand)
        self.assertIsNone(home["quality"])
        self.assertEqual(home["spent"], 2000)
        self.assertIsNotNone(home["pace"])
        self.assertEqual(home["money"]["purchases"], 3)


class CounterexampleTest(_Pinned):
    def setUp(self):
        super().setUp()
        self.brand = _brand(self.conn, self.org, "首頁總覽：反例")

    def test_nothing_synced(self):
        home = self.overview(self.brand)
        self.assertIsNone(home["spent"])
        self.assertIsNone(home["currency"])
        self.assertIsNone(home["quality"])
        self.assertEqual(home["money"]["purchases"], None)
        self.assertIsNone(home["money"]["earn_after_cost_and_ads"])
        self.assertEqual(home["money"]["earn_missing"], ["no_purchase_campaign"])
        self.assertTrue(all(d["cumulative"] is None for d in home["pace"]["daily"]))
        self.assertIsNone(home["pace"]["projected_month_end"])
        self.assertEqual(home["campaigns"], [])
        self.assertEqual(home["sync"], {"last_success_at": None, "next_at": None})

    def test_zero_purchases_is_a_known_loss_and_no_cost_per_purchase(self):
        conn, org, brand = self.conn, self.org, self.brand
        product = _product(conn, brand, unit_variable_cost=150)
        campaign = _imported(conn, org, brand, "零購買", "c0", product_id=product)
        ad = _ad(conn, org, brand, campaign, "z1", "c0")
        _obs(conn, org, brand, campaign, ad, date(2026, 9, 3), spend=120, count=0)
        money = self.overview(brand)["money"]
        self.assertEqual(money["purchases"], 0)
        self.assertIsNone(money["cost_per_purchase"])
        self.assertEqual(money["earn_after_cost_and_ads"], -120)
        self.assertEqual(money["cap"], {"value": 300, "basis": "break_even", "break_even": 300})

    def test_null_spend_day_nulls_spent_but_not_other_campaigns(self):
        conn, org, brand = self.conn, self.org, self.brand
        good = _imported(conn, org, brand, "完整", "cg", cap=100)
        bad = _imported(conn, org, brand, "缺花費", "cb", cap=100)
        g1 = _ad(conn, org, brand, good, "g1", "cg")
        b1 = _ad(conn, org, brand, bad, "b1", "cb")
        _obs(conn, org, brand, good, g1, date(2026, 9, 4), spend=80, count=1)
        _obs(conn, org, brand, bad, b1, date(2026, 9, 4), spend=None, count=0)
        self.grades = {g1: "on_target", b1: "insufficient"}
        home = self.overview(brand)
        self.assertIsNone(home["spent"])
        self.assertEqual(home["currency"], "TWD")
        self.assertIsNone(home["quality"])
        self.assertTrue(all(d["cumulative"] is None for d in home["pace"]["daily"]))
        self.assertIsNone(home["pace"]["projected_month_end"])
        rows = {c["campaign_id"]: c for c in home["campaigns"]}
        self.assertEqual(rows[good]["month_spend"], 80)
        self.assertIsNone(rows[bad]["month_spend"])
        self.assertIsNone(home["money"]["cost_per_purchase"])
        self.assertIsNone(home["money"]["earn_after_cost_and_ads"])
        self.assertIn("spend", home["money"]["earn_missing"])

    def test_mixed_currencies_are_never_summed(self):
        conn, org, brand = self.conn, self.org, self.brand
        tw = _imported(conn, org, brand, "台幣", "ctw", cap=100)
        us = _imported(conn, org, brand, "美金", "cus", cap=100)
        t1 = _ad(conn, org, brand, tw, "t1", "ctw")
        u1 = _ad(conn, org, brand, us, "u1", "cus")
        _obs(conn, org, brand, tw, t1, date(2026, 9, 4), spend=80, count=1)
        _obs(conn, org, brand, us, u1, date(2026, 9, 4), spend=5, count=1, currency="USD")
        home = self.overview(brand)
        self.assertIsNone(home["spent"])
        self.assertIsNone(home["currency"])
        self.assertIsNone(home["quality"])
        self.assertTrue(all(c["month_spend"] is None for c in home["campaigns"]))
        self.assertEqual(home["money"]["purchases"], 2)  # counts are not money
        self.assertIsNone(home["money"]["cost_per_purchase"])
        self.assertIsNone(home["money"]["earn_after_cost_and_ads"])

    def test_no_cap_anywhere_and_no_break_even(self):
        conn, org, brand = self.conn, self.org, self.brand
        campaign = _imported(conn, org, brand, "沒上限", "cn")
        ad = _ad(conn, org, brand, campaign, "n1", "cn")
        _obs(conn, org, brand, campaign, ad, date(2026, 9, 4), spend=90, count=3)
        self.grades = {ad: "no_target"}
        home = self.overview(brand)
        self.assertIsNone(home["money"]["cap"])
        self.assertEqual(home["money"]["cost_per_purchase"], 30)
        self.assertIsNone(home["money"]["earn_after_cost_and_ads"])  # unknown, never 0
        self.assertEqual(home["money"]["earn_missing"], ["product"])
        self.assertIsNone(home["campaigns"][0]["cap"])
        buckets = {b["grade"]: b["amount"] for b in home["quality"]["buckets"]}
        self.assertEqual(buckets["no_target"], 90)

    def test_result_kind_unknown_is_excluded_not_guessed(self):
        conn, org, brand = self.conn, self.org, self.brand
        campaign = _imported(conn, org, brand, "未知成果", "cu", result_kind=None)
        ad = _ad(conn, org, brand, campaign, "u1", "cu")
        _obs(conn, org, brand, campaign, ad, date(2026, 9, 4), spend=90, count=3)
        money = self.overview(brand)["money"]
        self.assertIsNone(money["purchases"])
        self.assertEqual(money["excluded"], [
            {"campaign_id": campaign, "name": "未知成果", "reason": "result_kind_unknown"},
        ])

    def test_monthly_budget_feeds_pace(self):
        conn, org, brand = self.conn, self.org, self.brand
        month_budget.save(conn, org, brand, month=MONTH, currency="TWD", amount=60000,
                          expected_revision=0, actor="test")
        pace = self.overview(brand)["pace"]
        self.assertEqual(pace["budget_amount"], 60000)
        # No connected account to reconcile against: the remainder stays unknown.
        self.assertIsNone(pace["available"])
        # F51 Contract F: served, never rebuilt by the browser -- 60,000 × 23 ÷ 30.
        self.assertEqual(pace["budget_to_date"], 46000)

    def test_budget_to_date_rounds_half_up(self):
        """45 × 23 ÷ 30 = 34.5 -> 35 (`budget.whole`, half up; Python's `round` would give 34)."""
        month_budget.save(self.conn, self.org, self.brand, month=MONTH, currency="TWD",
                          amount=45, expected_revision=0, actor="test")
        self.assertEqual(self.overview(self.brand)["pace"]["budget_to_date"], 35)

    def test_draft_with_no_ads_is_listed_after_live_rows(self):
        conn, org, brand = self.conn, self.org, self.brand
        live = _imported(conn, org, brand, "在投", "cl", cap=100)
        ad = _ad(conn, org, brand, live, "v1", "cl")
        _obs(conn, org, brand, live, ad, date(2026, 9, 4), spend=90, count=3)
        draft = repository.create_campaign(conn, org, brand, {
            "name": "秋季新色預購", "goal_text": "預購", "objective": "購買",
            "start_date": date(2026, 10, 1), "end_date": date(2026, 10, 31),
        })["id"]
        conn.commit()
        home = self.overview(brand)
        self.assertEqual([c["campaign_id"] for c in home["campaigns"]], [live, draft])
        row = home["campaigns"][1]
        self.assertEqual(row["draft"], {
            "start_date": "2026-10-01", "cap_missing": True, "ads_total": 0, "ads_ready": 0,
            "approved": False,
        })
        self.assertIsNone(row["month_spend"])
        self.assertEqual(row["active_ads"], 0)
        start = [i for i in home["timeline"] if i["kind"] == "campaign_start"]
        self.assertEqual(start, [{"date": "2026-10-01", "kind": "campaign_start",
                                  "campaign_id": draft, "name": "秋季新色預購",
                                  "ready": False}])

    def test_draft_ads_ready_uses_the_launch_material_check(self):
        conn, org, brand = self.conn, self.org, self.brand
        draft = repository.create_campaign(conn, org, brand, {
            "name": "草稿", "goal_text": "g", "objective": "購買", "target_cost": 200,
            "start_date": date(2026, 9, 28),
        })["id"]
        group = repository.create_group(conn, org, brand, draft, channel_key="meta", name="A",
                                        role="new", daily_budget=400)["id"]
        first = repository.create_ad(conn, org, brand, draft, group, name="一",
                                     coordinates={}, coordinates_snapshot={})["id"]
        second = repository.create_ad(conn, org, brand, draft, group, name="二",
                                      coordinates={}, coordinates_snapshot={})["id"]
        # A manual 就位 tick without a confirmed material binding is not ready (F30-I16).
        repository.set_ad_asset_ready(conn, org, brand, second, actor="t", ready=True)
        conn.commit()

        def snapshot(conn_, org_, brand_, campaign_, ad, **_kw):
            if ad["id"] == first:
                return {"assignment_status": "confirmed"}
            return None

        with (
            mock.patch.object(handoff_assignment, "material_snapshot", side_effect=snapshot),
            mock.patch.object(
                change_control_launch, "ready_material", wraps=change_control_launch.ready_material
            ) as ready,
        ):
            row = self.overview(brand)["campaigns"][0]
        self.assertEqual(row["draft"]["ads_total"], 2)
        self.assertEqual(row["draft"]["ads_ready"], 1)
        # The count is the launch batch's own predicate, not a copy of it.
        self.assertEqual(ready.call_count, 2)
        self.assertFalse(row["draft"]["cap_missing"])
        self.assertEqual(row["daily_budget"], 400)

    def test_daily_budget_counts_only_owners_with_an_active_ad(self):
        """ads.md §6.34 (2026-09-26): a live group whose ads are all paused is not in the total --
        the same rule as the workspace capacity."""
        conn, org, brand = self.conn, self.org, self.brand
        live = _imported(conn, org, brand, "兩組", "c2", cap=100)
        for adset, amount, ad, status in (("s_run", 300, "run", "ACTIVE"),
                                          ("s_idle", 500, "idle", "PAUSED")):
            external.upsert_entity(conn, org, brand, live, {
                "platform": "meta", "source_account": "act_1", "native_kind": "adset",
                "native_id": adset, "parent_native_kind": "campaign", "parent_native_id": "c2",
                "native_status": "ACTIVE", "budget_type": "daily", "budget_amount": amount,
                "currency": "TWD",
            })
            external.upsert_entity(conn, org, brand, live, {
                "platform": "meta", "source_account": "act_1", "native_kind": "ad",
                "native_id": ad, "name": ad, "native_status": status,
                "parent_native_kind": "adset", "parent_native_id": adset,
            })
        conn.commit()
        row = next(c for c in self.overview(brand)["campaigns"] if c["campaign_id"] == live)
        self.assertEqual(row["active_ads"], 1)
        self.assertEqual(row["daily_budget"], 300)

    def test_day_one_has_no_complete_day(self):
        conn, org, brand = self.conn, self.org, self.brand
        campaign = _imported(conn, org, brand, "月初", "c1", cap=100)
        ad = _ad(conn, org, brand, campaign, "d1", "c1")
        _obs(conn, org, brand, campaign, ad, date(2026, 9, 1), spend=70, count=1)  # today
        with _pinned(date(2026, 9, 1)):
            home = self.overview(brand)
        self.assertEqual(home["day_of_month"], 1)
        self.assertIsNone(home["spent"])
        self.assertEqual(home["pace"]["daily"], [])
        self.assertIsNone(home["pace"]["projected_month_end"])
        self.assertIsNone(home["money"]["previous_same_period"])


class _Clock(datetime):
    now_utc = datetime(2026, 9, 30, 17, 0, tzinfo=UTC)  # 2026-10-01 01:00 in Asia/Taipei

    @classmethod
    def now(cls, tz=None):
        return cls.now_utc.astimezone(tz) if tz else cls.now_utc.replace(tzinfo=None)


class MonthEndTimezoneTest(unittest.TestCase):
    """The org's own day decides the month: 17:00 UTC on 9/30 is already 10/1 in Taipei."""

    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = _brand(self.conn, self.org, "首頁總覽：月底時區")
        campaign = _imported(self.conn, self.org, self.brand, "跨月", "ctz", cap=100)
        ad = _ad(self.conn, self.org, self.brand, campaign, "tz1", "ctz")
        _obs(self.conn, self.org, self.brand, campaign, ad, date(2026, 9, 30), spend=70,
             count=1)
        classify = mock.patch.object(triage, "classify", return_value={"items": []})
        clock = mock.patch.object(db, "now_utc", return_value=_Clock.now_utc)
        bound = _bound_meta()
        classify.start()
        clock.start()
        bound.start()
        self.addCleanup(classify.stop)
        self.addCleanup(clock.stop)
        self.addCleanup(bound.stop)

    def test_route_defaults_to_the_org_month(self):
        from fastapi.testclient import TestClient

        from app import main

        self.assertEqual(coresettings.DEFAULT_ORG_TIMEZONE, "Asia/Taipei")
        client = TestClient(main.app)
        response = client.get(f"/api/ads/brands/{self.brand}/home")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIn("month", body, body)
        self.assertEqual(body["month"], "2026-10")
        self.assertEqual(body["day_of_month"], 1)
        self.assertIsNone(body["spent"])

    def test_the_last_day_of_september_is_complete(self):
        home = home_overview.get_overview(self.conn, self.org, self.brand, "2026-09")
        self.assertEqual(home["day_of_month"], 30)
        self.assertEqual(home["spent"], 70)  # 9/30 counts: in Taipei it is already over
        self.assertEqual(home["pace"]["daily"][-1], {"day": "2026-09-30", "cumulative": 70})
        self.assertEqual(home["pace"]["projected_month_end"], 70)


class RouteTest(unittest.TestCase):
    def test_route_is_wired_and_rejects_a_bad_month(self):
        from fastapi.testclient import TestClient

        from app import main

        conn, org = db.current(), db.DEV_ORG_ID
        brand = _brand(conn, org, "首頁總覽：路由")
        client = TestClient(main.app)
        with mock.patch.object(triage, "classify", return_value={"items": []}):
            ok = client.get(f"/api/ads/brands/{brand}/home?month={MONTH}")
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(set(ok.json()), {
            "month", "day_of_month", "days_in_month", "currency", "spent", "money", "pace",
            "quality", "timeline", "campaigns", "sync", "closed_this_month",
        })
        bad = client.get(f"/api/ads/brands/{brand}/home?month=2026-9")
        self.assertEqual(bad.status_code, 422, bad.text)


class SyncBlockTest(_Pinned):
    def test_last_success_and_next_read(self):
        brand = _brand(self.conn, self.org, "首頁總覽：同步")
        success = datetime(2026, 9, 23, 0, 40, tzinfo=UTC)
        updated = datetime(2026, 9, 23, 0, 45, tzinfo=UTC)
        self.conn.execute(
            "INSERT INTO ads_external_sync_job(id,org_id,brand_id,platform,source_account,status,"
            "last_success_at,updated_at) VALUES(%s,%s,%s,'meta','act_1','succeeded',%s,%s)",
            (db.new_id("aes"), self.org, brand, success, updated),
        )
        self.conn.commit()
        sync = self.overview(brand)["sync"]
        self.assertEqual(sync["last_success_at"], success)
        self.assertEqual(sync["next_at"], updated + timedelta(hours=6))


class RealTriageTest(unittest.TestCase):
    """No triage stub: each ad lands in exactly the bucket the real `triage.classify` grades it,
    and the buckets still add up to `spent`."""

    def test_buckets_follow_real_triage_grades(self):
        conn, org = db.current(), db.DEV_ORG_ID
        brand = _brand(conn, org, "首頁總覽：真的分級")
        campaign = _imported(conn, org, brand, "真分級", "cr", cap=100)
        active = _ad(conn, org, brand, campaign, "r1", "cr")
        closed = _ad(conn, org, brand, campaign, "r2", "cr", status="PAUSED")
        _obs(conn, org, brand, campaign, active, date(2026, 9, 3), spend=500, count=0)
        _obs(conn, org, brand, campaign, closed, date(2026, 9, 4), spend=40, count=1)
        grade = {i["entity_id"]: i["grade"]
                 for i in triage.classify(conn, org, brand, campaign)["items"]}
        self.assertEqual(set(grade), {active})
        with _pinned(TODAY), _bound_meta():
            home = home_overview.get_overview(conn, org, brand, MONTH)
        buckets = {b["grade"]: b for b in home["quality"]["buckets"]}
        self.assertEqual(buckets[grade[active]]["ads"][0]["entity_id"], active)
        self.assertEqual(buckets["ungraded"]["ads"][0]["entity_id"], closed)
        self.assertEqual(sum(b["amount"] for b in buckets.values()), home["spent"])
        self.assertEqual(home["spent"], 540)
