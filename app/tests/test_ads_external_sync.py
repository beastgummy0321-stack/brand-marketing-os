"""Real isolated PostgreSQL + fake source capability, no platform writes or LLM."""

import unittest
from datetime import UTC, date, datetime, timedelta
from datetime import time as dt_time
from unittest.mock import patch

from app.ads import external_repository as repo
from app.ads import external_sync as sync
from app.ads import tracked_zero
from app.ads.adapters.external import SourcePage
from app.brand_intelligence import repository as brands
from app.core import db, settings


def setup_brand(conn):
    org = db.DEV_ORG_ID
    brand = brands.create_brand(conn, org_id=org, name="來源測試", client_name=None, actor="test")[
        "id"
    ]
    conn.commit()
    return org, brand


class Reader:
    def __init__(self):
        self.connected = True
        self.calls = []
        self.fail_second = False

    def accounts(self, conn, org, brand):
        return (
            [
                {
                    "account_id": "account",
                    "currency": "TWD",
                    "name": "來源",
                    "timezone_name": "Asia/Taipei",
                }
            ]
            if self.connected
            else []
        )

    def read_monthly(self, conn, org, brand, account, *, start, end, **kwargs):
        return SourcePage(
            [],
            coverage={
                "scope": "account_campaign_day",
                "start": start,
                "end": end,
                "account_id": account["account_id"],
                "currency": account["currency"],
                "timezone_name": account["timezone_name"],
            },
        )

    def root(self, native_id="root", **values):
        return {
            "platform": "other",
            "source_account": "account",
            "native_kind": "portfolio",
            "native_id": native_id,
            "name": "暫停但存在",
            "native_status": "PAUSED",
            **values,
        }

    def list_existing(self, *args, cursor=None, **kwargs):
        self.calls.append(("list", cursor))
        if cursor and self.fail_second:
            raise ValueError("private-provider-message")
        return SourcePage(
            [self.root("second" if cursor else "root")], None if cursor else {"after": "page2"}
        )

    def read_structure(self, *args, native_id, **kwargs):
        self.calls.append(("structure", None))
        return SourcePage(
            [
                self.root(native_id),
                self.root(
                    "child",
                    native_kind="line",
                    parent_native_kind="portfolio",
                    parent_native_id=native_id,
                ),
            ]
        )

    def read_creatives(self, *args, **kwargs):
        return SourcePage(
            [
                {
                    "platform": "other",
                    "source_account": "account",
                    "native_kind": "line",
                    "native_id": "child",
                    "creative": {"kind": "video", "video_original": None},
                }
            ]
        )

    # F16-I04: a stand-in for a real platform adapter's own objective -> result-kind mapping
    # (`app.ads.adapters.meta_read.MetaReader.result_kind`) -- exercises the same seam
    # `external_sync._fill_result_kind_if_null` calls through, without depending on Meta's own
    # objective vocabulary.
    _RESULT_KIND_MAP = {"SALES": "purchase", "ENGAGE": "engagement"}

    def result_kind(self, entity):
        return self._RESULT_KIND_MAP.get(entity.get("objective"))

    def read_observations(self, *args, start, **kwargs):
        return SourcePage(
            [
                {
                    "native_kind": "line",
                    "native_id": "child",
                    "day": start,
                    "metric_scope": "line",
                    "attribution_key": "own-window",
                    "currency": "TWD",
                    "source": "other",
                    "spend": 0,
                    "purchases": None,
                }
            ]
        )


class ExternalSyncTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.org, self.brand = setup_brand(self.conn)
        self.reader = Reader()
        self.patches = [
            patch.object(sync.channels, "external_reader", return_value=self.reader),
            patch.object(sync.background, "enqueue", return_value=True),
            patch.object(sync.background, "is_active", return_value=False),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def run_pages(self, job):
        for _ in range(12):
            sync.run_sync(self.org, self.brand, job["id"])
            job = repo.get_job(self.conn, self.org, self.brand, job["id"])
            if job["status"] not in {"pending", "running"}:
                return job
        self.fail("cursor did not terminate")

    def test_second_page_failure_resumes_and_preserves_cache(self):
        self.reader.fail_second = True
        job = sync.request_sync(self.conn, self.org, self.brand, "other", "account")
        job = self.run_pages(job)
        self.assertEqual(job["status"], "partial")
        self.assertEqual(job["tasks"]["list"]["cursor"], {"after": "page2"})
        self.assertEqual(
            len(repo.listing(self.conn, self.org, self.brand, "other", "account")["items"]), 1
        )
        self.assertNotIn("private-provider-message", str(job))
        self.reader.fail_second = False
        job = self.run_pages(sync.request_sync(self.conn, self.org, self.brand, "other", "account"))
        self.assertEqual(job["status"], "succeeded")
        self.assertIsNone(job["tasks"]["list"].get("error_code"))
        self.assertEqual(
            len(repo.listing(self.conn, self.org, self.brand, "other", "account")["items"]), 2
        )
        self.assertEqual(self.reader.calls[-1], ("list", {"after": "page2"}))

    def test_generic_adapter_import_and_source_observations(self):
        self.run_pages(sync.request_sync(self.conn, self.org, self.brand, "other", "account"))
        first = repo.import_cached(
            self.conn, self.org, self.brand, "other", "account", "portfolio", "root", "test"
        )
        self.conn.commit()
        duplicate = repo.import_cached(
            self.conn, self.org, self.brand, "other", "account", "portfolio", "root", "test"
        )
        self.assertEqual(first["id"], duplicate["id"])
        self.conn.commit()
        job = self.run_pages(sync.request_sync(self.conn, self.org, self.brand, "other", "account"))
        self.assertEqual(job["status"], "succeeded", job["tasks"])
        view = repo.external_view(self.conn, self.org, self.brand, first["id"])
        self.assertEqual(len(view["entities"]), 2)
        self.assertEqual(view["observations"][0]["spend"], 0)
        self.assertIsNone(view["observations"][0]["purchases"])

    def test_result_kind_and_count_flow_through_generic_sync(self):
        self.run_pages(sync.request_sync(self.conn, self.org, self.brand, "other", "account"))
        campaign = repo.import_cached(
            self.conn, self.org, self.brand, "other", "account", "portfolio", "root", "test"
        )
        self.conn.commit()
        with patch.object(
            self.reader,
            "read_observations",
            return_value=SourcePage(
                [
                    {
                        "native_kind": "line",
                        "native_id": "child",
                        "day": date(2026, 1, 1),
                        "metric_scope": "line",
                        "attribution_key": "own-window",
                        "currency": "TWD",
                        "source": "other",
                        "spend": 0,
                        "purchases": None,
                        "result_kind": "lead",
                        "result_count": 3,
                    }
                ]
            ),
        ):
            job = self.run_pages(
                sync.request_sync(self.conn, self.org, self.brand, "other", "account")
            )
        self.assertEqual(job["status"], "succeeded", job["tasks"])
        view = repo.external_view(
            self.conn,
            self.org,
            self.brand,
            campaign["id"],
            start=date(2026, 1, 1),
            end=date(2026, 1, 1),
        )
        self.assertEqual(view["observations"][0]["result_kind"], "lead")
        self.assertEqual(view["observations"][0]["result_count"], 3)

    def test_run_sync_derives_tracked_zero_once_observations_complete_cleanly(self):
        # F18-I01: the one call site is `run_sync`, in the same transaction the "observations"
        # section records its coverage -- never a separate background step.
        self.run_pages(sync.request_sync(self.conn, self.org, self.brand, "other", "account"))
        campaign = repo.import_cached(
            self.conn, self.org, self.brand, "other", "account", "portfolio", "root", "test"
        )
        self.conn.commit()
        today = settings.today_for_org(self.conn, org_id=self.org)
        demo_day, target_day = today - timedelta(days=3), today - timedelta(days=1)
        with patch.object(
            self.reader,
            "read_observations",
            return_value=SourcePage(
                [
                    {
                        "native_kind": "line",
                        "native_id": "child",
                        "day": demo_day,
                        "metric_scope": "line",
                        "attribution_key": "demo",
                        "currency": "TWD",
                        "source": "other",
                        "spend": 100,
                        "purchases": None,
                        "result_kind": "lead",
                        "result_count": 5,
                        "result_action": "lead_form",
                        "result_attribution": "7d_click",
                    },
                    {
                        "native_kind": "line",
                        "native_id": "child",
                        "day": target_day,
                        "metric_scope": "line",
                        "attribution_key": "target",
                        "currency": "TWD",
                        "source": "other",
                        "spend": 50,
                        "purchases": None,
                        "result_kind": "lead",
                        "result_count": None,
                    },
                ]
            ),
        ):
            job = self.run_pages(
                sync.request_sync(
                    self.conn, self.org, self.brand, "other", "account",
                    start=demo_day, end=target_day,
                )
            )
        self.assertEqual(job["status"], "succeeded", job["tasks"])
        view = repo.external_view(
            self.conn, self.org, self.brand, campaign["id"], start=target_day, end=target_day
        )
        row = next(r for r in view["observations"] if r["attribution_key"] == "target")
        self.assertEqual(row["result_count"], 0)
        self.assertEqual(row["result_action"], "lead_form")
        self.assertEqual(row["result_attribution"], "7d_click")
        self.assertEqual(row["availability"]["result_count"], "derived_zero")

    def test_tracked_zero_failure_reports_derive_failed_not_a_source_read_failure(self):
        # F18-I01 review fix: the platform read itself already succeeded here -- a bug in our own
        # derivation rule must surface as its own error_code, never conflated with a real source
        # read problem (`invalid_source_page`/`source_error`/etc).
        self.run_pages(sync.request_sync(self.conn, self.org, self.brand, "other", "account"))
        repo.import_cached(
            self.conn, self.org, self.brand, "other", "account", "portfolio", "root", "test"
        )
        self.conn.commit()
        with patch.object(tracked_zero, "apply", side_effect=RuntimeError("boom")):
            job = self.run_pages(
                sync.request_sync(self.conn, self.org, self.brand, "other", "account")
            )
        self.assertEqual(job["status"], "partial")
        observations_key = next(k for k in job["tasks"] if ":observations:" in k)
        self.assertEqual(job["tasks"][observations_key]["error_code"], "derive_failed")

    def test_zero_derivation_cutoff_uses_account_timezone_not_org_timezone(self):
        # F18-I01 review fix: pick a moment where the org (Asia/Taipei, UTC+8) has already rolled
        # over to a new day but a UTC-8 account has not -- the org's "yesterday" is still today in
        # the account's own timezone, so that day must stay undecided (not derived) under the
        # account's clock, even though the org-based cutoff would have allowed it.
        real_today = settings.today_for_org(self.conn, org_id=self.org)
        moment = datetime.combine(real_today, dt_time(1, 0), tzinfo=UTC)
        org_yesterday = real_today - timedelta(days=1)  # still "today" for the UTC-8 account
        demo_day = org_yesterday - timedelta(days=3)

        original_accounts = self.reader.accounts

        def accounts_with_offset_tz(conn, org, brand):
            return [
                {**a, "timezone_name": "Etc/GMT+8"} for a in original_accounts(conn, org, brand)
            ]

        with patch.object(self.reader, "accounts", side_effect=accounts_with_offset_tz):
            self.run_pages(sync.request_sync(self.conn, self.org, self.brand, "other", "account"))
            campaign = repo.import_cached(
                self.conn, self.org, self.brand, "other", "account", "portfolio", "root", "test"
            )
            self.conn.commit()
            with patch.object(sync, "now_utc", return_value=moment), patch.object(
                self.reader,
                "read_observations",
                return_value=SourcePage(
                    [
                        {
                            "native_kind": "line",
                            "native_id": "child",
                            "day": demo_day,
                            "metric_scope": "line",
                            "attribution_key": "demo",
                            "currency": "TWD",
                            "source": "other",
                            "spend": 100,
                            "purchases": None,
                            "result_kind": "lead",
                            "result_count": 5,
                            "result_action": "lead_form",
                            "result_attribution": "7d_click",
                        },
                        {
                            "native_kind": "line",
                            "native_id": "child",
                            "day": org_yesterday,
                            "metric_scope": "line",
                            "attribution_key": "target",
                            "currency": "TWD",
                            "source": "other",
                            "spend": 50,
                            "purchases": None,
                            "result_kind": "lead",
                            "result_count": None,
                        },
                    ]
                ),
            ):
                job = self.run_pages(
                    sync.request_sync(
                        self.conn, self.org, self.brand, "other", "account",
                        start=demo_day, end=org_yesterday,
                    )
                )
            self.assertEqual(job["status"], "succeeded", job["tasks"])
            view = repo.external_view(
                self.conn, self.org, self.brand, campaign["id"],
                start=org_yesterday, end=org_yesterday,
            )
        row = next(r for r in view["observations"] if r["attribution_key"] == "target")
        self.assertIsNone(row["result_count"])

    def test_resync_heals_row_superseded_by_a_changed_attribution_key(self):
        # F16-I06 cause #2: a platform's `attribution_key` can embed something that changes
        # between reads of the very same identity (entity, day, metric_scope, currency, source) --
        # Meta's embeds the purchase action type, so a day first read before any purchase lands
        # is stored under one key and a later re-sync after a purchase stores it under another.
        # The DB's uniqueness key treats that as two rows; a re-sync must heal its own duplicate.
        self.run_pages(sync.request_sync(self.conn, self.org, self.brand, "other", "account"))
        campaign = repo.import_cached(
            self.conn, self.org, self.brand, "other", "account", "portfolio", "root", "test"
        )
        self.conn.commit()
        day = date(2026, 1, 1)

        def page(attribution_key, spend):
            return SourcePage(
                [
                    {
                        "native_kind": "line",
                        "native_id": "child",
                        "day": day,
                        "metric_scope": "line",
                        "attribution_key": attribution_key,
                        "currency": "TWD",
                        "source": "other",
                        "spend": spend,
                        "purchases": None,
                    }
                ]
            )

        with patch.object(
            self.reader, "read_observations", return_value=page("window:unavailable", 722)
        ):
            job = self.run_pages(
                sync.request_sync(
                    self.conn, self.org, self.brand, "other", "account", start=day, end=day
                )
            )
        self.assertEqual(job["status"], "succeeded", job["tasks"])
        with patch.object(
            self.reader, "read_observations", return_value=page("window:omni_purchase", 1747)
        ):
            job = self.run_pages(
                sync.request_sync(
                    self.conn, self.org, self.brand, "other", "account", start=day, end=day
                )
            )
        self.assertEqual(job["status"], "succeeded", job["tasks"])
        view = repo.external_view(
            self.conn, self.org, self.brand, campaign["id"], start=day, end=day
        )
        rows = [r for r in view["observations"] if r["day"] == day]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["spend"], 1747)
        self.assertEqual(rows[0]["attribution_key"], "window:omni_purchase")

    def test_monthly_write_never_heals_or_is_healed_by_an_observation_row(self):
        # Monthly-budget rows are a different grain entirely (F16-I06) -- the healing that repairs
        # cause #2 must never delete or be triggered by them.
        self.run_pages(sync.request_sync(self.conn, self.org, self.brand, "other", "account"))
        campaign = repo.import_cached(
            self.conn, self.org, self.brand, "other", "account", "portfolio", "root", "test"
        )
        self.conn.commit()
        entity = self.conn.execute(
            "SELECT id FROM ads_external_entity WHERE campaign_id=%s AND native_kind='portfolio'",
            (campaign["id"],),
        ).fetchone()
        day = date(2026, 1, 1)
        repo.upsert_observation(
            self.conn,
            self.org,
            self.brand,
            campaign["id"],
            {
                "entity_id": entity["id"],
                "day": day,
                "metric_scope": "portfolio",
                "attribution_key": repo.MONTHLY_BUDGET_ATTRIBUTION_KEY,
                "currency": "TWD",
                "source": "other",
                "spend": 1900,
            },
        )
        self.conn.commit()
        with patch.object(
            self.reader,
            "read_observations",
            return_value=SourcePage(
                [
                    {
                        "native_kind": "portfolio",
                        "native_id": "root",
                        "day": day,
                        "metric_scope": "portfolio",
                        "attribution_key": "own-window",
                        "currency": "TWD",
                        "source": "other",
                        "spend": 100,
                        "purchases": None,
                    }
                ]
            ),
        ):
            job = self.run_pages(
                sync.request_sync(
                    self.conn, self.org, self.brand, "other", "account", start=day, end=day
                )
            )
        self.assertEqual(job["status"], "succeeded", job["tasks"])
        view = repo.external_view(
            self.conn, self.org, self.brand, campaign["id"], start=day, end=day
        )
        keys = {r["attribution_key"] for r in view["observations"] if r["day"] == day}
        self.assertEqual(keys, {"own-window", repo.MONTHLY_BUDGET_ATTRIBUTION_KEY})

    def test_heal_only_reaches_the_identity_it_replaces(self):
        # F16-I06 known limit: the heal treats ANY differing `attribution_key` of the same
        # identity as superseded, so the boundary of "same identity" is the whole safety
        # argument. `metric_scope`, `currency` and `source` are part of that identity -- a row
        # differing in any one of them is a different grain, not an older read of this one, and
        # must survive untouched. The same-identity row is seeded too, so this can never pass
        # by the heal simply not firing.
        self.run_pages(sync.request_sync(self.conn, self.org, self.brand, "other", "account"))
        campaign = repo.import_cached(
            self.conn, self.org, self.brand, "other", "account", "portfolio", "root", "test"
        )
        self.conn.commit()
        entity = self.conn.execute(
            "SELECT id FROM ads_external_entity WHERE campaign_id=%s AND native_kind='portfolio'",
            (campaign["id"],),
        ).fetchone()
        day = date(2026, 1, 1)
        for attribution_key, overrides in (
            ("stale-window", {}),  # same identity, older key -- the only row that may go
            ("other-scope", {"metric_scope": "line"}),
            ("other-currency", {"currency": "USD"}),
            ("other-source", {"source": "manual"}),
        ):
            repo.upsert_observation(
                self.conn,
                self.org,
                self.brand,
                campaign["id"],
                {
                    "entity_id": entity["id"],
                    "day": day,
                    "metric_scope": "portfolio",
                    "attribution_key": attribution_key,
                    "currency": "TWD",
                    "source": "other",
                    "spend": 100,
                }
                | overrides,
            )
        self.conn.commit()
        with patch.object(
            self.reader,
            "read_observations",
            return_value=SourcePage(
                [
                    {
                        "native_kind": "portfolio",
                        "native_id": "root",
                        "day": day,
                        "metric_scope": "portfolio",
                        "attribution_key": "own-window",
                        "currency": "TWD",
                        "source": "other",
                        "spend": 1747,
                        "purchases": None,
                    }
                ]
            ),
        ):
            job = self.run_pages(
                sync.request_sync(
                    self.conn, self.org, self.brand, "other", "account", start=day, end=day
                )
            )
        self.assertEqual(job["status"], "succeeded", job["tasks"])
        view = repo.external_view(
            self.conn, self.org, self.brand, campaign["id"], start=day, end=day
        )
        keys = {r["attribution_key"] for r in view["observations"] if r["day"] == day}
        self.assertEqual(keys, {"own-window", "other-scope", "other-currency", "other-source"})

    def _structure_page(self, native_id="root", *, objective):
        # Same two-entity shape `Reader.read_structure` returns by default (root + one child) --
        # only the root carries the objective a real platform's structure sync would report at
        # campaign level.
        return SourcePage([
            self.reader.root(native_id, objective=objective),
            self.reader.root(
                "child", native_kind="line", parent_native_kind="portfolio",
                parent_native_id=native_id,
            ),
        ])

    def test_sync_fills_result_kind_only_when_null_and_never_overwrites_a_user_choice(self):
        self.run_pages(sync.request_sync(self.conn, self.org, self.brand, "other", "account"))
        campaign = repo.import_cached(
            self.conn, self.org, self.brand, "other", "account", "portfolio", "root", "test"
        )
        self.conn.commit()

        with patch.object(
            self.reader, "read_structure",
            return_value=self._structure_page(objective="SALES"),
        ):
            job = self.run_pages(
                sync.request_sync(self.conn, self.org, self.brand, "other", "account")
            )
        self.assertEqual(job["status"], "succeeded", job["tasks"])
        row = self.conn.execute(
            "SELECT result_kind FROM ads_campaign WHERE id=%s", (campaign["id"],)
        ).fetchone()
        self.assertEqual(row["result_kind"], "purchase")

        # A user's own PUT choice, once stored, must survive a later re-sync untouched -- even
        # one that (from a stale platform read) would otherwise map to something else.
        from app.ads import repository as ads_repo

        ads_repo.save_campaign_target(
            self.conn, self.org, self.brand, campaign["id"],
            result_kind="lead", expected_revision=0, actor="test",
        )
        with patch.object(
            self.reader, "read_structure",
            return_value=self._structure_page(objective="ENGAGE"),
        ):
            job = self.run_pages(
                sync.request_sync(self.conn, self.org, self.brand, "other", "account")
            )
        self.assertEqual(job["status"], "succeeded", job["tasks"])
        row = self.conn.execute(
            "SELECT result_kind FROM ads_campaign WHERE id=%s", (campaign["id"],)
        ).fetchone()
        self.assertEqual(row["result_kind"], "lead")

    def test_revoked_account_blocks_pending_read_without_erasing_data(self):
        job = self.run_pages(sync.request_sync(self.conn, self.org, self.brand, "other", "account"))
        job = sync.request_sync(self.conn, self.org, self.brand, "other", "account")
        self.reader.connected = False
        job = self.run_pages(job)
        self.assertEqual(job["status"], "partial")
        self.assertEqual(
            len(repo.listing(self.conn, self.org, self.brand, "other", "account")["items"]), 2
        )
        with self.assertRaisesRegex(ValueError, "解除"):
            sync.request_sync(self.conn, self.org, self.brand, "other", "account")

    def test_requests_merge_and_jobs_remain_brand_scoped(self):
        job = sync.request_sync(self.conn, self.org, self.brand, "other", "account")
        again = sync.request_sync(self.conn, self.org, self.brand, "other", "account")
        self.assertEqual(job["id"], again["id"])
        _, other = setup_brand(self.conn)
        separate = sync.request_sync(self.conn, self.org, other, "other", "account")
        self.assertNotEqual(job["id"], separate["id"])
        with self.assertRaises(ValueError):
            repo.get_job(self.conn, self.org, other, job["id"])

    def test_worker_refreshes_snapshot_after_lock(self):
        job = sync.request_sync(self.conn, self.org, self.brand, "other", "account")
        original = repo.get_job
        calls = 0

        def stale_first(conn, org, brand, job_id):
            nonlocal calls
            current = original(conn, org, brand, job_id)
            calls += 1
            if calls == 1:
                conn.execute(
                    "UPDATE ads_external_sync_job SET tasks=%s,status='succeeded' WHERE id=%s",
                    (
                        db.jsonb(
                            {"list": {"section": "list", "status": "succeeded", "cursor": None}}
                        ),
                        job_id,
                    ),
                )
                conn.commit()
            return current

        with patch.object(repo, "get_job", side_effect=stale_first):
            sync.run_sync(self.org, self.brand, job["id"])
        self.assertEqual(self.reader.calls, [])
        self.assertEqual(
            original(self.conn, self.org, self.brand, job["id"])["status"], "succeeded"
        )

    def test_parallel_import_returns_one_workspace(self):
        from concurrent.futures import ThreadPoolExecutor

        self.run_pages(sync.request_sync(self.conn, self.org, self.brand, "other", "account"))
        self.conn.commit()

        def do_import():
            with db.connection() as conn:
                result = repo.import_cached(
                    conn, self.org, self.brand, "other", "account", "portfolio", "root", "test"
                )
                conn.commit()
                return result["id"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(lambda _: do_import(), range(2)))
        self.assertEqual(ids[0], ids[1])

    def test_partial_creative_failure_retains_prior_success(self):
        self.run_pages(sync.request_sync(self.conn, self.org, self.brand, "other", "account"))
        campaign = repo.import_cached(
            self.conn, self.org, self.brand, "other", "account", "portfolio", "root", "test"
        )
        self.conn.commit()
        self.run_pages(sync.request_sync(self.conn, self.org, self.brand, "other", "account"))
        prior = repo.external_view(self.conn, self.org, self.brand, campaign["id"])
        with patch.object(self.reader, "read_creatives", side_effect=ValueError("failed")):
            job = self.run_pages(
                sync.request_sync(self.conn, self.org, self.brand, "other", "account")
            )
        view = repo.external_view(self.conn, self.org, self.brand, campaign["id"])
        self.assertEqual(job["status"], "partial")
        self.assertEqual(
            view["sync"]["creatives"]["last_success_at"],
            prior["sync"]["creatives"]["last_success_at"],
        )
        self.assertEqual(
            [e["creative"] for e in view["entities"]], [e["creative"] for e in prior["entities"]]
        )

    def test_new_window_request_during_read_is_not_overwritten(self):
        self.run_pages(sync.request_sync(self.conn, self.org, self.brand, "other", "account"))
        campaign = repo.import_cached(
            self.conn, self.org, self.brand, "other", "account", "portfolio", "root", "test"
        )
        self.conn.commit()
        job = sync.request_sync(self.conn, self.org, self.brand, "other", "account")
        original = self.reader.list_existing

        def append_request(*args, **kwargs):
            with db.connection() as conn:
                sync.request_sync(
                    conn,
                    self.org,
                    self.brand,
                    "other",
                    "account",
                    start=date(2026, 1, 1),
                    end=date(2026, 1, 2),
                )
            return original(*args, **kwargs)

        with patch.object(self.reader, "list_existing", side_effect=append_request):
            sync.run_sync(self.org, self.brand, job["id"])
        current = repo.get_job(self.conn, self.org, self.brand, job["id"])
        key = campaign["id"] + ":observations:2026-01-01:2026-01-02"
        self.assertEqual(current["tasks"][key]["status"], "pending")

    def test_legacy_binding_reused_only_for_its_platform_and_kind(self):
        from app.ads import repository

        self.run_pages(sync.request_sync(self.conn, self.org, self.brand, "other", "account"))
        campaign = repository.create_campaign(
            self.conn,
            self.org,
            self.brand,
            {"name": "內部", "goal_text": "目標", "objective": "購買", "success_metric": "cpa"},
        )
        repository.bind_campaign(
            self.conn,
            self.org,
            self.brand,
            campaign["id"],
            external_id="root",
            external_name="來源",
            external_status="PAUSED",
        )
        self.conn.commit()
        foreign = repo.import_cached(
            self.conn, self.org, self.brand, "other", "account", "portfolio", "root", "test"
        )
        self.assertNotEqual(foreign["id"], campaign["id"])
        repo.cache_listing(
            self.conn,
            self.org,
            self.brand,
            "meta",
            "account",
            self.reader.root() | {"platform": "meta", "native_kind": "campaign"},
        )
        result = repo.import_cached(
            self.conn, self.org, self.brand, "meta", "account", "campaign", "root", "test"
        )
        self.assertEqual(result["id"], campaign["id"])
        self.assertEqual(result["origin"], "internal")

    def test_contending_account_job_remains_durable_until_unlock(self):
        job = sync.request_sync(self.conn, self.org, self.brand, "other", "account")
        lock = f"external-account:{self.org}:other:account"
        with db.connection() as holder:
            holder.execute("SELECT pg_advisory_lock(hashtextextended(%s,0))", (lock,))
            holder.commit()
            try:
                sync.run_sync(self.org, self.brand, job["id"])
                self.assertEqual(self.reader.calls, [])
                self.assertEqual(
                    repo.get_job(self.conn, self.org, self.brand, job["id"])["status"], "pending"
                )
            finally:
                holder.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (lock,))
                holder.commit()
        result = self.run_pages(job)
        self.assertEqual(result["status"], "succeeded")
