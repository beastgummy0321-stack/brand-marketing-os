"""app/tests/test_ads_workspace_reads.py — F30-I06 (Contract E) falsifiers for the campaign
workspace reads: `campaign_stage.stage`, `GET …/workspace`, `…/structure`, `…/timeline`.

Counterexamples: a draft at each of its three stages; a live campaign with a gap in its synced
days (`read`, never `decide`); live with and without an open queue row (a row of another campaign
of the same brand never counts); closed; a failed sub-read that must read null (never 0, never a
promoted stage); the 14-day window in the org timezone with a zero-spend day; an imported
structure; an app-built structure with a matched platform ad and a replacement the plan does not
hold; timeline ties on equal `created_at`, the omitted sets, every state and truncation.
"""

import unittest
from datetime import UTC, date, datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

from app.ads import (
    campaign_stage,
    change_control_launch,
    channels,
    handoff_assignment,
    home_overview,
    repository,
    slots,
    triage,
    workspace_reads,
)
from app.ads import external_repository as external
from app.brand_intelligence import repository as bi_repo
from app.core import db
from app.core import settings as coresettings

ACCOUNT_TZ = "Asia/Taipei"


class _Reader:
    """One bound account `act_1` with a known timezone (not `disconnected`, a fixed cutoff)."""

    def accounts(self, conn, org, brand):
        return [{"account_id": "act_1", "currency": "TWD", "name": "來源",
                 "timezone_name": ACCOUNT_TZ}]


def _brand(conn, org, name):
    brand = bi_repo.create_brand(conn, org_id=org, name=name, actor="test", client_name=None)
    conn.commit()
    return brand["id"]


def _entity(conn, org, brand, campaign_id, kind, native_id, parent=None, **extra):
    row = {"platform": "meta", "source_account": "act_1", "native_kind": kind,
           "native_id": native_id, "name": native_id, **extra}
    if parent is not None:
        row["parent_native_kind"], row["parent_native_id"] = parent
    return external.upsert_entity(conn, org, brand, campaign_id, row)["id"]


def _imported(conn, org, brand, name, native_id, *, cap=None):
    campaign_id = external.create_imported_campaign(conn, org, brand, name=name)["id"]
    _entity(conn, org, brand, campaign_id, "campaign", native_id)
    conn.commit()
    if cap is not None:
        repository.save_campaign_target(
            conn, org, brand, campaign_id, result_kind="purchase", basis="own", value=cap,
            expected_revision=0, actor="test",
        )
        conn.commit()
    return campaign_id


def _ad(conn, org, brand, campaign_id, native_id, parent, *, status="ACTIVE"):
    entity_id = _entity(conn, org, brand, campaign_id, "ad", native_id, parent,
                        native_status=status)
    conn.commit()
    return entity_id


def _obs(conn, org, brand, campaign_id, ad_id, day, *, spend, count=0):
    external.upsert_observation(
        conn, org, brand, campaign_id,
        {"entity_id": ad_id, "day": day, "metric_scope": "ad", "attribution_key": "a",
         "currency": "TWD", "source": "meta", "spend": spend, "impressions": 100,
         "purchases": None},
        result_kind="purchase", result_count=count, result_action="omni_purchase",
        result_attribution="7d_click+1d_view",
    )
    conn.commit()


def _synced(conn, org, brand, campaign_id, start, end):
    """The campaign's recorded read ranges become exactly `[start, end]` (F49 Contract V:
    `record_sync` keeps a union, so the earlier ranges are cleared first)."""
    conn.execute(
        "UPDATE ads_campaign SET context_json = context_json "
        "#- '{external_sync,observations,ranges}' WHERE id=%s",
        (campaign_id,),
    )
    external.record_sync(
        conn, org, brand, campaign_id, section="observations",
        state={"status": "success", "last_success_at": db.now_utc().isoformat(),
               "coverage": {"start": start.isoformat(), "end": end.isoformat()}},
    )
    conn.commit()


def _draft(conn, org, brand, name="秋季新色預購", **fields):
    campaign_id = repository.create_campaign(conn, org, brand, {
        "name": name, "goal_text": "g", "objective": "購買",
        "start_date": date(2026, 10, 1), "end_date": date(2026, 10, 31), **fields,
    })["id"]
    conn.commit()
    return campaign_id


_BASE = datetime(2026, 9, 20, 6, 0, tzinfo=UTC)


def _set(conn, org, brand, campaign_id, *, status="approved", states=(), created=_BASE,
         plan=None, reason=None, kind="budget", title="變更"):
    """One change set with `ads_action` items in `states`; returns (set id, action ids)."""
    set_id = db.new_id("acs")
    conn.execute(
        "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,request_hash,"
        "content_hash,title,month,plan_json,created_by,status,decision_reason,created_at,"
        "approved_at) VALUES(%s,%s,%s,%s,%s,'h','h',%s,'2026-09',%s,'test',%s,%s,%s,%s)",
        (set_id, org, brand, campaign_id, db.new_id("op"), title,
         db.jsonb(plan if plan is not None else {"items": [{"id": "x"}]}), status, reason,
         created, created if status == "approved" else None),
    )
    actions = []
    for state in states:
        action_id = db.new_id("adx")
        conn.execute(
            "INSERT INTO ads_action(id,org_id,brand_id,campaign_id,target_kind,target_id,kind,"
            "change_set_id,verification_state) VALUES(%s,%s,%s,%s,'campaign',%s,%s,%s,%s)",
            (action_id, org, brand, campaign_id, campaign_id, kind, set_id, state),
        )
        actions.append(action_id)
    conn.commit()
    return set_id, actions


def _handoff_item(conn, org, brand, campaign_id, set_id, action_id, planned_kind, planned_id,
                  *, status="pending", entity_id=None):
    conn.execute(
        "INSERT INTO ads_handoff_item(id,org_id,brand_id,campaign_id,change_set_id,action_id,"
        "planned_kind,planned_id,name,expected_json,entity_id,status) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'n','{}',%s,%s)",
        (db.new_id("ahi"), org, brand, campaign_id, set_id, action_id, planned_kind, planned_id,
         entity_id, status),
    )
    conn.commit()


def _launch(conn, org, brand, campaign_id, *, handoff=(), version=None, created=_BASE):
    """An approved launch set frozen from the current plan, with one handoff item per
    `(planned_kind, planned_id, status, entity_id)` in `handoff`."""
    plan = {"items": [], "launch_snapshot": change_control_launch.snapshot(
        conn, org, brand, campaign_id)}
    if version is not None:
        plan["version"] = version
    set_id, (action,) = _set(conn, org, brand, campaign_id, states=["pending"], plan=plan,
                             kind="publish", title="首次投放人工交接", created=created)
    for planned_kind, planned_id, status, entity_id in handoff:
        _handoff_item(conn, org, brand, campaign_id, set_id, action, planned_kind, planned_id,
                      status=status, entity_id=entity_id)
    return set_id


class _WithReader(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        patcher = mock.patch.object(channels, "external_reader", return_value=_Reader())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cutoff = (db.now_utc().astimezone(ZoneInfo(ACCOUNT_TZ)) - timedelta(days=1)).date()

    def workspace(self, brand, campaign_id):
        return workspace_reads.workspace(self.conn, self.org, brand, campaign_id)


# ---------------------------------------------------------------------------
# The one stage function
# ---------------------------------------------------------------------------


class StageFunctionTest(unittest.TestCase):
    def stage(self, **facts):
        base = {"state": "live", "launch_approved": False, "cap_set": False,
                "data_ready": True, "open_items": 0}
        return campaign_stage.stage(**{**base, **facts})

    def test_draft_plan_assets_launch(self):
        self.assertEqual(self.stage(state="draft"), {"key": "plan", "done": []})
        self.assertEqual(self.stage(state="draft", cap_set=True),
                         {"key": "assets", "done": ["plan"]})
        self.assertEqual(self.stage(state="draft", launch_approved=True),
                         {"key": "launch", "done": ["plan", "assets"]})

    def test_launched_read_and_decide(self):
        self.assertEqual(self.stage()["key"], "read")
        self.assertEqual(self.stage(open_items=2),
                         {"key": "decide", "done": ["plan", "assets", "launch", "read"]})
        self.assertEqual(self.stage(open_items=2, data_ready=False)["key"], "read")

    def test_unknown_never_promotes(self):
        self.assertEqual(self.stage(open_items=None)["key"], "read")
        self.assertEqual(self.stage(open_items=3, data_ready=None)["key"], "read")

    def test_ended_waits_on_review_and_closed_is_review_done(self):
        # F49 Contract L: an ended campaign's waiting step is its closeout; a closed one is done.
        self.assertEqual(self.stage(state="ended", open_items=4),
                         {"key": "review", "done": ["plan", "assets", "launch", "read", "decide"]})
        self.assertEqual(self.stage(state="closed", open_items=4),
                         {"key": "review",
                          "done": ["plan", "assets", "launch", "read", "decide", "review"]})


# ---------------------------------------------------------------------------
# workspace
# ---------------------------------------------------------------------------


class DraftWorkspaceTest(_WithReader):
    def setUp(self):
        super().setUp()
        self.brand = _brand(self.conn, self.org, "工作區：草稿")

    def test_plan_without_a_cap(self):
        draft = _draft(self.conn, self.org, self.brand)
        ws = self.workspace(self.brand, draft)
        self.assertEqual(ws["stage"], {"key": "plan", "done": []})
        self.assertEqual(ws["pending_count"], 0)
        self.assertEqual(ws["active_ads"], 0)
        self.assertIsNone(ws["totals"])
        self.assertIsNone(ws["daily_budget"])  # no group yet: unknown, not 0
        self.assertIsNone(ws["can_support"])
        self.assertEqual(ws["missing_days"], [])  # nothing on a platform to miss
        self.assertEqual(ws["draft"], {
            "cap_set": False, "budget_set": False, "slots_ready": 0, "slots_total": 0,
            "launch_checked": 0, "launch_total": 0,
        })

    def test_assets_once_the_cap_is_set(self):
        draft = _draft(self.conn, self.org, self.brand, target_cost=200)
        group = repository.create_group(self.conn, self.org, self.brand, draft,
                                        channel_key="meta", name="A", role="new",
                                        daily_budget=400)["id"]
        first = repository.create_ad(self.conn, self.org, self.brand, draft, group, name="一",
                                     coordinates={}, coordinates_snapshot={})["id"]
        repository.create_ad(self.conn, self.org, self.brand, draft, group, name="二",
                             coordinates={}, coordinates_snapshot={})
        self.conn.execute("UPDATE ads_campaign SET budget_planned=12000 WHERE id=%s", (draft,))
        self.conn.commit()

        def snapshot(conn_, org_, brand_, campaign_, ad, **_kw):
            return {"assignment_status": "confirmed"} if ad["id"] == first else None

        with mock.patch.object(handoff_assignment, "material_snapshot", side_effect=snapshot):
            ws = self.workspace(self.brand, draft)
        self.assertEqual(ws["stage"], {"key": "assets", "done": ["plan"]})
        self.assertEqual(ws["daily_budget"], 400)
        self.assertEqual(ws["draft"], {
            "cap_set": True, "budget_set": True, "slots_ready": 1, "slots_total": 2,
            "launch_checked": 0, "launch_total": 0,
        })

    def test_launch_once_approved_counts_its_handoff_items(self):
        draft = _draft(self.conn, self.org, self.brand)
        _launch(self.conn, self.org, self.brand, draft, handoff=[
            ("campaign", draft, "confirmed", None), ("group", "g1", "pending", None),
            ("ad", "a1", "reported", None),
        ])
        ws = self.workspace(self.brand, draft)
        self.assertEqual(ws["stage"], {"key": "launch", "done": ["plan", "assets"]})
        self.assertEqual((ws["draft"]["launch_checked"], ws["draft"]["launch_total"]), (1, 3))

    def test_draft_stage_matches_the_home_row(self):
        draft = _draft(self.conn, self.org, self.brand, target_cost=200)
        with mock.patch.object(coresettings, "today_for_org", return_value=date(2026, 9, 23)):
            home = home_overview.get_overview(self.conn, self.org, self.brand, "2026-09")
        row = next(r for r in home["campaigns"] if r["campaign_id"] == draft)
        ws = self.workspace(self.brand, draft)
        self.assertIsNotNone(row["draft"])
        self.assertEqual(ws["draft"]["cap_set"], not row["draft"]["cap_missing"])
        self.assertEqual(ws["stage"]["key"], "assets")


class LiveWorkspaceTest(_WithReader):
    def setUp(self):
        super().setUp()
        self.brand = _brand(self.conn, self.org, "工作區：在投")
        self.campaign = _imported(self.conn, self.org, self.brand, "日常轉換", "c_live", cap=100)
        self.ad = _ad(self.conn, self.org, self.brand, self.campaign, "a_live",
                      ("campaign", "c_live"))

    def test_gap_in_the_synced_days_is_read(self):
        _synced(self.conn, self.org, self.brand, self.campaign,
                self.cutoff - timedelta(days=3), self.cutoff)
        _obs(self.conn, self.org, self.brand, self.campaign, self.ad, self.cutoff, spend=500)
        ws = self.workspace(self.brand, self.campaign)
        self.assertEqual(ws["stage"]["key"], "read")
        self.assertEqual(ws["active_ads"], 1)
        self.assertIsNone(ws["draft"])
        status = triage.classify(self.conn, self.org, self.brand, self.campaign)["data"]["status"]
        self.assertEqual(status["state"], "partial")
        self.assertTrue(ws["missing_days"])
        self.assertEqual(ws["missing_days"], status["missing_days"])
        self.assertLess(ws["missing_days"][-1], (self.cutoff - timedelta(days=3)).isoformat())

    def test_ready_without_open_items_is_read(self):
        _synced(self.conn, self.org, self.brand, self.campaign,
                self.cutoff - timedelta(days=90), self.cutoff)
        _obs(self.conn, self.org, self.brand, self.campaign, self.ad, self.cutoff, spend=50,
             count=1)
        ws = self.workspace(self.brand, self.campaign)
        self.assertEqual(ws["pending_count"], 0)
        self.assertEqual(ws["stage"], {"key": "read", "done": ["plan", "assets", "launch"]})
        self.assertEqual(ws["missing_days"], [])

    def test_open_queue_row_is_decide_and_another_campaigns_row_does_not_count(self):
        other = _imported(self.conn, self.org, self.brand, "別的活動", "c_other", cap=100)
        other_ad = _ad(self.conn, self.org, self.brand, other, "a_other", ("campaign", "c_other"))
        for campaign_id, ad in ((self.campaign, self.ad), (other, other_ad)):
            _synced(self.conn, self.org, self.brand, campaign_id,
                    self.cutoff - timedelta(days=90), self.cutoff)
            # 500 spent, no purchase, cap 100: 沒賣出 -> the campaign's cleanup row.
            _obs(self.conn, self.org, self.brand, campaign_id, ad, self.cutoff, spend=500)
        queue = triage.refresh_queue(self.conn, self.org, self.brand)
        rows = [r for r in queue["items"] if r["kind_key"] == "cleanup"]
        self.assertEqual({r["triage"]["campaign_id"] for r in rows}, {self.campaign, other})
        ws = self.workspace(self.brand, self.campaign)
        self.assertEqual(ws["pending_count"], 1)
        self.assertEqual(ws["stage"]["key"], "decide")

    def test_a_confirmed_cleanup_is_not_waiting(self):
        """drill-11 controls/c3-06 (F49 Contract Q): the cleanup set was approved and its pause
        read back `confirmed` -- the row the queue still serves is done, so the workspace counts
        no open decision and the stage is not 決定."""
        second = _ad(self.conn, self.org, self.brand, self.campaign, "a_live2",
                     ("campaign", "c_live"))
        _synced(self.conn, self.org, self.brand, self.campaign,
                self.cutoff - timedelta(days=90), self.cutoff)
        for ad in (self.ad, second):
            _obs(self.conn, self.org, self.brand, self.campaign, ad, self.cutoff, spend=500)
        queue = triage.refresh_queue(self.conn, self.org, self.brand)
        [row] = [r for r in queue["items"] if r["kind_key"] == "cleanup"]
        self.assertEqual({ad["entity_id"] for ad in row["cleanup"]["ads"]}, {self.ad, second})
        # The user closed the first ad; the readback confirmed it and the platform read shows it
        # paused (the second one stays proposed, outside this set).
        action_id = db.new_id("adx")
        set_id, _ = _set(self.conn, self.org, self.brand, self.campaign, plan={
            "source": "cleanup",
            "items": [{"id": action_id, "kind": "pause", "target_id": self.ad}],
        })
        self.conn.execute(
            "INSERT INTO ads_action(id,org_id,brand_id,campaign_id,target_kind,target_id,kind,"
            "change_set_id,verification_state) VALUES(%s,%s,%s,%s,'ad',%s,'pause',%s,'confirmed')",
            (action_id, self.org, self.brand, self.campaign, self.ad, set_id),
        )
        _entity(self.conn, self.org, self.brand, self.campaign, "ad", "a_live",
                ("campaign", "c_live"), native_status="PAUSED")
        self.conn.commit()
        [served] = [r for r in triage.get_queue(self.conn, self.org, self.brand)["items"]
                    if r["kind_key"] == "cleanup"]
        self.assertTrue(served["done"])
        ws = self.workspace(self.brand, self.campaign)
        self.assertEqual(ws["pending_count"], 0)
        self.assertNotEqual(ws["stage"]["key"], "decide")

    def test_the_brand_settle_row_is_not_this_campaigns(self):
        # F49 Contract Q: rows carry their `campaign_id` (None on the brand's settle row) and
        # only open decision rows count -- a notice or a done row does not.
        rows = [{"kind_key": "settle", "campaign_id": None, "done": False},
                {"kind_key": "worse", "campaign_id": self.campaign, "done": False},
                {"kind_key": "closeout", "campaign_id": self.campaign, "done": False},
                {"kind_key": "cleanup", "campaign_id": self.campaign, "done": True},
                {"kind_key": "scale_budget", "campaign_id": self.campaign, "done": False},
                {"kind_key": "worse", "campaign_id": "another_campaign", "done": False}]
        with mock.patch.object(triage, "get_queue", return_value={"items": rows}) as queue:
            count = workspace_reads._open_queue_count(
                self.conn, self.org, self.brand, self.campaign, [{"entity_id": self.ad}],
            )
        self.assertEqual(count, 2)
        self.assertEqual(queue.call_args.kwargs["items"], [{"entity_id": self.ad}])

    def test_the_count_never_grades_the_brand_month_for_a_settle_row_it_drops(self):
        with mock.patch.object(triage, "_settle_candidates", return_value=[]) as settle:
            workspace_reads._open_queue_count(self.conn, self.org, self.brand, self.campaign, [])
            triage.get_queue(self.conn, self.org, self.brand, items=[])
        self.assertEqual(settle.call_count, 1, "only the brand queue grades the month")

    def test_closed_is_review(self):
        self.conn.execute("UPDATE ads_campaign SET status='closed' WHERE id=%s",
                          (self.campaign,))
        self.conn.commit()
        ws = self.workspace(self.brand, self.campaign)
        self.assertEqual(ws["stage"]["key"], "review")
        self.assertEqual(ws["pending_count"], 0)

    def test_capacity_is_one_rule_for_daily_budget_and_can_support(self):
        adset = _entity(self.conn, self.org, self.brand, self.campaign, "adset", "s1",
                        ("campaign", "c_live"), budget_type="daily", budget_amount=900,
                        currency="TWD")
        self.conn.commit()
        _ad(self.conn, self.org, self.brand, self.campaign, "a_set", ("adset", "s1"))
        self.conn.execute("DELETE FROM ads_external_entity WHERE id=%s", (self.ad,))
        self.conn.commit()
        self.assertTrue(adset)
        ws = self.workspace(self.brand, self.campaign)
        self.assertEqual(ws["daily_budget"], 900)
        self.assertEqual(ws["can_support"], 4)  # floor(900 / (100 × 2))
        capacity = triage.classify(self.conn, self.org, self.brand, self.campaign)["data"][
            "capacity"]
        self.assertEqual((ws["daily_budget"], ws["can_support"]),
                         (capacity["daily_budget"], capacity["can_support"]))


class FailedSubReadTest(_WithReader):
    def setUp(self):
        super().setUp()
        self.brand = _brand(self.conn, self.org, "工作區：讀取失敗")
        self.campaign = _imported(self.conn, self.org, self.brand, "讀取失敗", "c_fail", cap=100)
        self.ad = _ad(self.conn, self.org, self.brand, self.campaign, "a_fail",
                      ("campaign", "c_fail"))
        _synced(self.conn, self.org, self.brand, self.campaign,
                self.cutoff - timedelta(days=90), self.cutoff)
        _obs(self.conn, self.org, self.brand, self.campaign, self.ad, self.cutoff, spend=500)
        triage.refresh_queue(self.conn, self.org, self.brand)

    def test_a_failed_queue_read_is_null_and_never_decide(self):
        with mock.patch.object(triage, "get_queue", side_effect=RuntimeError("boom")):
            ws = self.workspace(self.brand, self.campaign)
        self.assertIsNone(ws["pending_count"])
        self.assertEqual(ws["stage"]["key"], "read")
        self.assertIsNotNone(ws["totals"])  # the other reads still answer

    def test_a_failed_triage_read_nulls_what_rests_on_it(self):
        with mock.patch.object(triage, "classify", side_effect=RuntimeError("boom")):
            ws = self.workspace(self.brand, self.campaign)
        self.assertIsNone(ws["pending_count"])
        self.assertIsNone(ws["daily_budget"])
        self.assertIsNone(ws["can_support"])
        self.assertIsNone(ws["missing_days"])  # unread, never "no day missing"
        self.assertEqual(ws["stage"]["key"], "read")
        self.assertEqual(ws["active_ads"], 1)

    def test_failed_totals_and_sync_reads_are_null(self):
        with mock.patch.object(workspace_reads, "_totals", side_effect=RuntimeError("boom")), \
                mock.patch.object(home_overview, "_sync_block", side_effect=RuntimeError("x")):
            ws = self.workspace(self.brand, self.campaign)
        self.assertIsNone(ws["totals"])
        self.assertIsNone(ws["next_sync_at"])
        self.assertEqual(ws["pending_count"], 1)

    def test_a_failed_draft_block_is_null(self):
        draft = _draft(self.conn, self.org, self.brand)
        with mock.patch.object(home_overview, "_draft_view", side_effect=RuntimeError("boom")):
            ws = self.workspace(self.brand, draft)
        self.assertIsNone(ws["draft"])
        self.assertEqual(ws["stage"]["key"], "plan")


class _Clock(datetime):
    now_utc = datetime(2026, 9, 23, 17, 0, tzinfo=UTC)  # 2026-09-24 01:00 in Asia/Taipei

    @classmethod
    def now(cls, tz=None):
        return cls.now_utc.astimezone(tz) if tz else cls.now_utc.replace(tzinfo=None)


class TotalsWindowTest(_WithReader):
    """The org's own day decides the window: at 17:00 UTC on 9/23 it is already 9/24 in Taipei,
    so the last complete day is 9/23 and the window is 9/10–9/23."""

    def test_fourteen_days_in_the_org_timezone_with_a_zero_spend_day(self):
        brand = _brand(self.conn, self.org, "工作區：14 天")
        campaign = _imported(self.conn, self.org, brand, "十四天", "c_14", cap=100)
        ad = _ad(self.conn, self.org, brand, campaign, "a_14", ("campaign", "c_14"))
        _obs(self.conn, self.org, brand, campaign, ad, date(2026, 9, 9), spend=999, count=9)
        _obs(self.conn, self.org, brand, campaign, ad, date(2026, 9, 10), spend=100, count=1)
        _obs(self.conn, self.org, brand, campaign, ad, date(2026, 9, 15), spend=0, count=0)
        _obs(self.conn, self.org, brand, campaign, ad, date(2026, 9, 23), spend=50, count=1)
        _obs(self.conn, self.org, brand, campaign, ad, date(2026, 9, 24), spend=777, count=7)
        # Every day of the window was read; the days without a row spent nothing.
        _synced(self.conn, self.org, brand, campaign, date(2026, 8, 1), date(2026, 9, 24))
        with mock.patch.object(db, "now_utc", return_value=_Clock.now_utc):
            ws = self.workspace(brand, campaign)
        self.assertEqual(ws["totals"], {
            "start": "2026-09-10", "end": "2026-09-23", "currency": "TWD", "spend": 150,
            "results": 2, "cost_per_result": 75,
        })

    def test_an_unread_day_in_the_window_nulls_every_number(self):
        # Rows only on read days; the unread days have no row at all -- they must never read as
        # zero spend (which would shrink spend and cost per result).
        brand = _brand(self.conn, self.org, "工作區：窗口缺日")
        campaign = _imported(self.conn, self.org, brand, "窗口缺日", "c_gap", cap=100)
        ad = _ad(self.conn, self.org, brand, campaign, "a_gap", ("campaign", "c_gap"))
        _obs(self.conn, self.org, brand, campaign, ad, date(2026, 9, 14), spend=100, count=1)
        _obs(self.conn, self.org, brand, campaign, ad, date(2026, 9, 20), spend=80, count=1)
        for coverage in ((date(2026, 9, 13), date(2026, 9, 23)),   # 9/10–9/12 never read
                         (date(2026, 8, 1), date(2026, 9, 21))):   # 9/22–9/23 never read
            with self.subTest(coverage=coverage):
                _synced(self.conn, self.org, brand, campaign, *coverage)
                with mock.patch.object(db, "now_utc", return_value=_Clock.now_utc):
                    totals = self.workspace(brand, campaign)["totals"]
                self.assertEqual((totals["start"], totals["end"]), ("2026-09-10", "2026-09-23"))
                self.assertEqual(
                    (totals["spend"], totals["results"], totals["cost_per_result"]),
                    (None, None, None),
                )
        _synced(self.conn, self.org, brand, campaign, date(2026, 9, 10), date(2026, 9, 23))
        with mock.patch.object(db, "now_utc", return_value=_Clock.now_utc):
            totals = self.workspace(brand, campaign)["totals"]
        self.assertEqual((totals["spend"], totals["results"], totals["cost_per_result"]),
                         (180, 2, 90))

    def test_rows_without_any_recorded_coverage_are_unknown(self):
        brand = _brand(self.conn, self.org, "工作區：沒有讀取紀錄")
        campaign = _imported(self.conn, self.org, brand, "沒讀過", "c_nocov", cap=100)
        ad = _ad(self.conn, self.org, brand, campaign, "a_nocov", ("campaign", "c_nocov"))
        _obs(self.conn, self.org, brand, campaign, ad, date(2026, 9, 14), spend=100, count=1)
        with mock.patch.object(db, "now_utc", return_value=_Clock.now_utc):
            totals = self.workspace(brand, campaign)["totals"]
        self.assertIsNone(totals["spend"])
        self.assertIsNone(totals["cost_per_result"])

    def test_an_unknown_day_nulls_spend_and_no_rows_is_unknown(self):
        brand = _brand(self.conn, self.org, "工作區：未知花費")
        campaign = _imported(self.conn, self.org, brand, "未知", "c_unk", cap=100)
        _synced(self.conn, self.org, brand, campaign, date(2026, 8, 1), date(2026, 9, 23))
        with mock.patch.object(db, "now_utc", return_value=_Clock.now_utc):
            empty = self.workspace(brand, campaign)["totals"]
        self.assertIsNone(empty["spend"])
        self.assertIsNone(empty["results"])
        ad = _ad(self.conn, self.org, brand, campaign, "a_unk", ("campaign", "c_unk"))
        _obs(self.conn, self.org, brand, campaign, ad, date(2026, 9, 12), spend=100, count=1)
        external.upsert_observation(
            self.conn, self.org, brand, campaign,
            {"entity_id": ad, "day": date(2026, 9, 13), "metric_scope": "ad",
             "attribution_key": "a", "currency": "TWD", "source": "meta", "spend": None,
             "impressions": 100, "purchases": None},
            result_kind="purchase", result_count=1, result_action="omni_purchase",
            result_attribution="7d_click+1d_view",
        )
        self.conn.commit()
        with mock.patch.object(db, "now_utc", return_value=_Clock.now_utc):
            totals = self.workspace(brand, campaign)["totals"]
        self.assertIsNone(totals["spend"])
        self.assertEqual(totals["currency"], "TWD")


class DeliveryTest(_WithReader):
    """F47 Contract E (drill-10 S3): `delivery` tells "on the platform, not spending yet" from
    "spending"; a draft, a closed campaign or a failed read is null (never promoted)."""

    def setUp(self):
        super().setUp()
        self.brand = _brand(self.conn, self.org, "工作區：投放狀態")
        self.campaign = _imported(self.conn, self.org, self.brand, "剛上架", "c_dlv", cap=100)
        self.ad = _ad(self.conn, self.org, self.brand, self.campaign, "a_dlv",
                      ("campaign", "c_dlv"))

    def delivery(self, campaign_id=None):
        return self.workspace(self.brand, campaign_id or self.campaign)["delivery"]

    def test_a_draft_is_null(self):
        self.assertIsNone(self.delivery(_draft(self.conn, self.org, self.brand)))

    def test_never_synced_since_launch_is_waiting(self):
        self.assertEqual(self.delivery(), "waiting")

    def test_only_zero_spend_rows_is_waiting(self):
        _synced(self.conn, self.org, self.brand, self.campaign,
                self.cutoff - timedelta(days=3), self.cutoff)
        for back in range(3):
            _obs(self.conn, self.org, self.brand, self.campaign, self.ad,
                 self.cutoff - timedelta(days=back), spend=0)
        self.assertEqual(self.delivery(), "waiting")

    def test_any_day_with_spend_is_live_even_outside_the_totals_window(self):
        _obs(self.conn, self.org, self.brand, self.campaign, self.ad,
             self.cutoff - timedelta(days=60), spend=12)
        self.assertEqual(self.delivery(), "live")

    def test_another_campaigns_spend_never_counts(self):
        other = _imported(self.conn, self.org, self.brand, "別的", "c_dlv2", cap=100)
        other_ad = _ad(self.conn, self.org, self.brand, other, "a_dlv2", ("campaign", "c_dlv2"))
        _obs(self.conn, self.org, self.brand, other, other_ad, self.cutoff, spend=500)
        self.assertEqual(self.delivery(), "waiting")
        self.assertEqual(self.delivery(other), "live")

    def test_an_internal_campaign_on_the_platform_reads_its_own_rows(self):
        internal = _draft(self.conn, self.org, self.brand, name="自建活動")
        _entity(self.conn, self.org, self.brand, internal, "campaign", "c_int")
        ad = _ad(self.conn, self.org, self.brand, internal, "a_int", ("campaign", "c_int"))
        self.assertEqual(self.delivery(internal), "waiting")
        _obs(self.conn, self.org, self.brand, internal, ad, self.cutoff, spend=30)
        self.assertEqual(self.delivery(internal), "live")

    def test_closed_is_null(self):
        _obs(self.conn, self.org, self.brand, self.campaign, self.ad, self.cutoff, spend=30)
        self.conn.execute("UPDATE ads_campaign SET status='closed' WHERE id=%s",
                          (self.campaign,))
        self.conn.commit()
        self.assertIsNone(self.delivery())

    def test_a_failed_spend_read_is_null(self):
        with mock.patch.object(workspace_reads, "_has_spent", side_effect=RuntimeError("boom")):
            ws = self.workspace(self.brand, self.campaign)
        self.assertIsNone(ws["delivery"])
        self.assertEqual(ws["active_ads"], 1)  # the other reads still answer


# ---------------------------------------------------------------------------
# structure
# ---------------------------------------------------------------------------


def _fake_sample(results):
    """A triage item's shown sample (F48 Contract R) for `results` sales."""
    return {"sales": results, "few": results is not None and 1 <= results < 5,
            "too_new": False, "spend_multiple": None, "days_with_events": 0}


def _fake_classify(grades):
    def classify(conn, org_id, brand_id, campaign_id):
        items = [
            {"entity_id": entity_id, "grade": grade, "grade_label": label,
             "reason_code": "too_new" if label == "剛開始、數字還不夠" else None,
             "sample": _fake_sample(results),
             "current": {"cost_per_result": cost, "result_count": results, "spend": spend}}
            for entity_id, (grade, label, cost, results, spend) in grades.items()
        ]
        return {"items": items}

    return classify


class ImportedStructureTest(_WithReader):
    def setUp(self):
        super().setUp()
        conn, org = self.conn, self.org
        self.brand = brand = _brand(conn, org, "工作區：結構（匯入）")
        self.campaign = _imported(conn, org, brand, "匯入活動", "c_imp", cap=100)
        _entity(conn, org, brand, self.campaign, "adset", "B 組", ("campaign", "c_imp"),
                budget_type="daily", budget_amount=300, currency="TWD")
        _entity(conn, org, brand, self.campaign, "adset", "A 組", ("campaign", "c_imp"),
                budget_type="lifetime", budget_amount=9000, currency="TWD")
        conn.commit()
        self.a1 = _ad(conn, org, brand, self.campaign, "甲", ("adset", "A 組"))
        self.a2 = _ad(conn, org, brand, self.campaign, "乙", ("adset", "A 組"))
        self.b1 = _ad(conn, org, brand, self.campaign, "丙", ("adset", "B 組"))
        self.gone = _ad(conn, org, brand, self.campaign, "丁", ("adset", "B 組"),
                        status="PAUSED")
        self.grades = {
            self.a1: ("on_target", "划算", 80.0, 5, 400.004),
            self.a2: ("wasted", "沒賣出", None, 0, 350.0),
            self.b1: ("insufficient", "剛開始、數字還不夠", None, None, None),
        }

    def structure(self):
        return workspace_reads.structure(self.conn, self.org, self.brand, self.campaign)

    def test_platform_parents_and_live_ads_with_their_triage_grades(self):
        _set_id, (pause,) = _set(self.conn, self.org, self.brand, self.campaign,
                                 states=["reported"], kind="pause")
        self.conn.execute("UPDATE ads_action SET target_kind='ad',target_id=%s WHERE id=%s",
                          (self.a2, pause))
        self.conn.commit()
        with mock.patch.object(triage, "classify", side_effect=_fake_classify(self.grades)):
            groups = self.structure()["groups"]
        self.assertEqual([(g["group_id"], g["name"], g["daily_budget"]) for g in groups],
                         [(None, "A 組", None), (None, "B 組", 300)])
        a_ads = groups[0]["ads"]
        self.assertEqual([a["name"] for a in a_ads], ["乙", "甲"])
        self.assertEqual(a_ads[1], {
            "ad_id": None, "entity_id": self.a1, "name": "甲", "thumbnail_url": None,
            "spend": 400.0, "grade": "on_target", "grade_label": "划算", "cost_per_result": 80.0,
            "reason_code": None, "sample": _fake_sample(5),
            "results": 5, "closing": False, "missing_material": False,
            "slot_state": None, "slot_label": None,
        })
        self.assertTrue(a_ads[0]["closing"])  # approved pause, readback not confirmed yet
        self.assertEqual(a_ads[0]["results"], 0)
        self.assertEqual(a_ads[0]["spend"], 350)  # 沒賣出: spend known, results a known 0
        self.assertEqual([a["entity_id"] for a in groups[1]["ads"]], [self.b1])  # 丁 is paused
        self.assertIsNone(groups[1]["ads"][0]["spend"])  # unknown stays null, never 0
        # F48: 剛開始 travels as its code, so the screen branches on `reason_code`, not the label.
        self.assertEqual(groups[1]["ads"][0]["reason_code"], "too_new")

    def test_a_confirmed_pause_is_not_closing(self):
        _set_id, (pause,) = _set(self.conn, self.org, self.brand, self.campaign,
                                 states=["confirmed"], kind="pause")
        self.conn.execute("UPDATE ads_action SET target_kind='ad',target_id=%s WHERE id=%s",
                          (self.a2, pause))
        self.conn.commit()
        with mock.patch.object(triage, "classify", side_effect=_fake_classify(self.grades)):
            groups = self.structure()["groups"]
        self.assertFalse(any(a["closing"] for g in groups for a in g["ads"]))

    def test_a_failed_triage_read_leaves_grades_null(self):
        with mock.patch.object(triage, "classify", side_effect=RuntimeError("boom")):
            groups = self.structure()["groups"]
        ads = [a for g in groups for a in g["ads"]]
        self.assertEqual(len(ads), 3)
        self.assertTrue(all(
            a["grade"] is None and a["results"] is None and a["spend"] is None for a in ads
        ))

    def test_real_triage_grade_is_the_structure_grade(self):
        _synced(self.conn, self.org, self.brand, self.campaign,
                self.cutoff - timedelta(days=90), self.cutoff)
        _obs(self.conn, self.org, self.brand, self.campaign, self.a2, self.cutoff, spend=500)
        items = {i["entity_id"]: i for i in
                 triage.classify(self.conn, self.org, self.brand, self.campaign)["items"]}
        ads = {a["entity_id"]: a for g in self.structure()["groups"] for a in g["ads"]}
        self.assertEqual(ads[self.a2]["grade"], "wasted")
        self.assertEqual(ads[self.a2]["spend"], 500)
        for entity_id, ad in ads.items():
            self.assertEqual(ad["grade"], items[entity_id]["grade"])
            self.assertEqual(ad["grade_label"], items[entity_id]["grade_label"])
            self.assertEqual(ad["spend"], items[entity_id]["current"]["spend"])
            self.assertEqual(ad["reason_code"], items[entity_id]["reason_code"])
            self.assertEqual(ad["sample"], items[entity_id]["sample"])


class AppBuiltStructureTest(_WithReader):
    def setUp(self):
        super().setUp()
        conn, org = self.conn, self.org
        self.brand = brand = _brand(conn, org, "工作區：結構（自建）")
        self.campaign = _draft(conn, org, brand, "自建活動", target_cost=100)
        self.group = repository.create_group(conn, org, brand, self.campaign,
                                             channel_key="meta", name="新客", role="new",
                                             daily_budget=400)["id"]
        self.ready = repository.create_ad(conn, org, brand, self.campaign, self.group,
                                          name="有素材", coordinates={},
                                          coordinates_snapshot={})["id"]
        self.missing = repository.create_ad(conn, org, brand, self.campaign, self.group,
                                            name="缺素材", coordinates={},
                                            coordinates_snapshot={})["id"]
        conn.commit()

    def slots_read(self, states):
        """`slots.read` (the one slot-state source, F49 Contract T) answering `states`."""
        def read(conn_, org_, brand_, campaign_):
            return {"groups": [{"slots": [
                {"ad_id": ad_id, "state": state, "state_label": label}
                for ad_id, (state, label) in states.items()
            ]}]}

        return mock.patch.object(slots, "read", side_effect=read)

    def test_draft_plan_groups_with_missing_material(self):
        # A manual 就位 tick without a confirmed material binding is still missing (F30-I16).
        repository.set_ad_asset_ready(self.conn, self.org, self.brand, self.missing,
                                      actor="t", ready=True)
        self.conn.commit()
        groups = workspace_reads.structure(self.conn, self.org, self.brand,
                                           self.campaign)["groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual((groups[0]["group_id"], groups[0]["name"], groups[0]["daily_budget"]),
                         (self.group, "新客", 400))
        # F49 Contract T: the real slot read decides -- neither ad has a file.
        self.assertEqual([(a["ad_id"], a["entity_id"], a["slot_state"], a["slot_label"],
                           a["missing_material"]) for a in groups[0]["ads"]],
                         [(self.ready, None, "missing", "缺", True),
                          (self.missing, None, "missing", "缺", True)])
        self.assertTrue(all(a["grade"] is None and a["spend"] is None
                            for a in groups[0]["ads"]))

    def test_the_structure_reads_each_planned_ads_slot_state_from_one_slots_read(self):
        """Audit W10 #4: one 缺素材 used to stand for six slot states. The structure serves the
        slot's own state and chip (one `slots.read`), `missing_material` only as not ready."""
        states = {self.ready: ("ready", "已確認"), self.missing: ("blocked", "卡住")}
        with self.slots_read(states) as read:
            groups = workspace_reads.structure(self.conn, self.org, self.brand,
                                               self.campaign)["groups"]
        self.assertEqual(read.call_count, 1)
        self.assertEqual([(a["ad_id"], a["slot_state"], a["slot_label"], a["missing_material"])
                          for a in groups[0]["ads"]],
                         [(self.ready, "ready", "已確認", False),
                          (self.missing, "blocked", "卡住", True)])

    def test_a_failed_slot_read_leaves_the_slot_state_null(self):
        with mock.patch.object(slots, "read", side_effect=RuntimeError("boom")):
            groups = workspace_reads.structure(self.conn, self.org, self.brand,
                                               self.campaign)["groups"]
        self.assertTrue(all(a["slot_state"] is None and a["missing_material"]
                            for a in groups[0]["ads"]))

    def test_launched_plan_ads_carry_their_platform_ad_and_a_replacement_joins_its_group(self):
        conn, org, brand, campaign = self.conn, self.org, self.brand, self.campaign
        _entity(conn, org, brand, campaign, "campaign", "c_app")
        adset = _entity(conn, org, brand, campaign, "adset", "s_app", ("campaign", "c_app"),
                        budget_type="daily", budget_amount=480, currency="TWD")
        conn.commit()
        bound = _ad(conn, org, brand, campaign, "p_ready", ("adset", "s_app"))
        extra = _ad(conn, org, brand, campaign, "p_new", ("adset", "s_app"))
        _launch(conn, org, brand, campaign, handoff=[
            ("group", self.group, "confirmed", adset), ("ad", self.ready, "confirmed", bound),
        ])
        grades = {bound: ("watch", "偏貴", 110.0, 12, 1320.0),
                  extra: ("on_target", "划算", 60.0, 20, 1200.0)}
        states = {self.ready: ("ready", "已確認"), self.missing: ("missing", "缺")}
        with self.slots_read(states), \
                mock.patch.object(triage, "classify", side_effect=_fake_classify(grades)):
            groups = workspace_reads.structure(conn, org, brand, campaign)["groups"]
        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertEqual(group["daily_budget"], 480)  # the platform budget, not the plan's 400
        ads = [(a["ad_id"], a["entity_id"], a["name"], a["grade"], a["missing_material"])
               for a in group["ads"]]
        self.assertEqual(ads, [
            (self.ready, bound, "有素材", "watch", False),
            (self.missing, None, "缺素材", None, True),
            (None, extra, "p_new", "on_target", False),
        ])


# ---------------------------------------------------------------------------
# timeline
# ---------------------------------------------------------------------------


class TimelineTest(_WithReader):
    def setUp(self):
        super().setUp()
        self.brand = _brand(self.conn, self.org, "工作區：變更紀錄")
        self.campaign = _imported(self.conn, self.org, self.brand, "變更", "c_tl", cap=100)

    def timeline(self, campaign_id=None):
        return workspace_reads.timeline(self.conn, self.org, self.brand,
                                        campaign_id or self.campaign)

    def at(self, minutes):
        return _BASE + timedelta(minutes=minutes)

    def test_equal_created_at_breaks_ties_by_id_desc(self):
        same = self.at(5)
        ids = [_set(self.conn, self.org, self.brand, self.campaign, states=["confirmed"],
                    created=same)[0] for _ in range(3)]
        older, _ = _set(self.conn, self.org, self.brand, self.campaign, states=["confirmed"],
                        created=self.at(1))
        rows = self.timeline()["rows"]
        self.assertEqual([r["change_set_id"] for r in rows], [*sorted(ids, reverse=True), older])

    def test_every_state_and_the_omitted_sets(self):
        c, o, b = self.campaign, self.org, self.brand
        platform, _ = _set(self.conn, o, b, c, states=["confirmed", "pending"],
                           created=self.at(7))
        check, _ = _set(self.conn, o, b, c, states=["confirmed", "deviated"], created=self.at(6))
        verified, _ = _set(self.conn, o, b, c, states=["confirmed", "confirmed"],
                           created=self.at(5))
        stale, _ = _set(self.conn, o, b, c, states=["confirmed", "stale"], created=self.at(4))
        draft, _ = _set(self.conn, o, b, c, status="draft",
                        plan={"items": [{"id": "1"}, {"id": "2"}]}, created=self.at(3))
        rejected, _ = _set(self.conn, o, b, c, status="rejected", reason="兩入組還在檔期",
                           created=self.at(2))
        _set(self.conn, o, b, c, status="superseded", created=self.at(9))
        _set(self.conn, o, b, c, status="deferred", created=self.at(8))
        body = self.timeline()
        self.assertFalse(body["truncated"])
        got = [(r["change_set_id"], r["state"], r["checked"], r["total"], r["reason"])
               for r in body["rows"]]
        self.assertEqual(got, [
            (platform, "platform", 1, 2, None), (check, "check", 1, 2, None),
            (verified, "verified", 2, 2, None), (stale, "stale", 1, 2, None),
            (draft, "draft", 0, 2, None), (rejected, "rejected", 0, 1, "兩入組還在檔期"),
        ])
        self.assertTrue(all(r["version"] is None for r in body["rows"]))

    def test_truncated_after_the_cap(self):
        for i in range(workspace_reads.TIMELINE_CAP + 1):
            _set(self.conn, self.org, self.brand, self.campaign, states=["confirmed"],
                 created=self.at(i))
        body = self.timeline()
        self.assertTrue(body["truncated"])
        self.assertEqual(len(body["rows"]), workspace_reads.TIMELINE_CAP)
        self.assertEqual(body["rows"][0]["at"], self.at(workspace_reads.TIMELINE_CAP))

    def test_launch_version_counts_and_stale(self):
        draft = _draft(self.conn, self.org, self.brand, "上架版本")
        launch = _launch(self.conn, self.org, self.brand, draft, version=2, handoff=[
            ("campaign", draft, "confirmed", None), ("group", "g", "confirmed", None),
            ("ad", "a", "pending", None),
        ])
        row = self.timeline(draft)["rows"][0]
        self.assertEqual((row["change_set_id"], row["state"], row["version"],
                          row["checked"], row["total"]), (launch, "platform", 2, 2, 3))
        self.conn.execute("UPDATE ads_campaign SET name='改過的名稱' WHERE id=%s", (draft,))
        self.conn.commit()
        self.assertTrue(change_control_launch.is_stale(self.conn, self.org, self.brand, draft))
        self.assertEqual(self.timeline(draft)["rows"][0]["state"], "stale")

    def test_first_launch_is_version_one(self):
        draft = _draft(self.conn, self.org, self.brand, "第一版")
        _launch(self.conn, self.org, self.brand, draft)
        self.assertEqual(self.timeline(draft)["rows"][0]["version"], 1)


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


class RouteTest(_WithReader):
    def test_routes_are_wired_and_an_unknown_campaign_is_404(self):
        from fastapi.testclient import TestClient

        from app import main

        brand = _brand(self.conn, self.org, "工作區：路由")
        draft = _draft(self.conn, self.org, brand)
        client = TestClient(main.app)
        base = f"/api/ads/brands/{brand}/campaigns"
        ws = client.get(f"{base}/{draft}/workspace")
        self.assertEqual(ws.status_code, 200, ws.text)
        self.assertEqual(set(ws.json()), {
            "stage", "pending_count", "delivery", "daily_budget", "active_ads", "can_support",
            "next_sync_at", "missing_days", "totals", "draft", "lifecycle", "running",
        })
        structure = client.get(f"{base}/{draft}/structure")
        self.assertEqual(structure.status_code, 200, structure.text)
        self.assertEqual(structure.json(), {"groups": []})
        timeline = client.get(f"{base}/{draft}/timeline")
        self.assertEqual(timeline.status_code, 200, timeline.text)
        self.assertEqual(timeline.json(), {"rows": [], "truncated": False})
        for path in ("workspace", "structure", "timeline"):
            with self.subTest(path=path):
                missing = client.get(f"{base}/adc_nope/{path}")
                self.assertEqual(missing.status_code, 404, missing.text)


if __name__ == "__main__":
    unittest.main()
