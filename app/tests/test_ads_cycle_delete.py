# -*- coding: utf-8 -*-
"""app/tests/test_ads_cycle_delete.py — 檔期封存＋真刪（issue #28，三道保護＋連帶後果明講）。

比照決策 0020 產品先例（app/tests/test_product_delete_routes.py）：三道保護——
未封存擋下、刪除頁輸入檔期名稱確認、名稱打錯不放行——外加刪除前自動備份。
額外守：任何狀態（PLANNING/LIVE/CLOSED…）都能封存／還原；刪除後連帶表無孤兒列；
封存清單預設不顯示、可切換檢視。

品牌與產品名一律虛構，絕不使用真實客戶品牌。
"""

import atexit
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_cycle_delete_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core.db import new_id  # noqa: E402

main.reopen_connection()


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"


class _BaseCycleDeleteTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.client.post("/settings/operator", data={"name": ACTOR, "next": "/"},
                          follow_redirects=False)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡（檔期刪除）",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        self.product_a = bi_repo.create_product(main.conn, self.bid, name="虛構濾掛組",
                                                 actor=ACTOR)["id"]

    def _open_cycle(self):
        resp = self.client.post(
            f"/brands/{self.bid}/ads/new",
            data={"product_ids": [self.product_a], "slider_index": "5", "objective": "sales"},
            follow_redirects=False,
        )
        cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]
        return cycle_id

    def _cycle_label(self, cycle_id):
        cycle = ads_repo.get_cycle(main.conn, self.bid, cycle_id)
        return f"{cycle['start_date']} ～ {cycle['end_date']}"

    def _seed_cascade_rows(self, cycle_id):
        """在檔期掛的每張連帶表都塞一列，才驗得出「刪乾淨」。只塞路由層碰不到、
        必須直接寫 SQL 才能造出資料的表；campaign_cycle_product 已經在開期時自動產生。
        每次呼叫都重新產生 id，同一支測試檔在同一顆共用連線上跑多個測試也不會撞到唯一鍵。"""
        conn = main.conn
        ts = "2026-01-01T00:00:00+00:00"
        fnd, rmd, cpo, dsn, chk, ccl = (new_id(p) for p in
                                        ("fnd", "rmd", "cpo", "dsn", "chk", "ccl"))
        exc, cbf, cvr, adp, fas, pkg = (new_id(p) for p in
                                        ("exc", "cbf", "cvr", "adp", "fas", "pkg"))
        xam, ath, act, psn, dmt, prd, rec, lrn = (new_id(p) for p in
                                                  ("xam", "ath", "act", "psn", "dmt", "prd",
                                                   "rec", "lrn"))
        vch, vcv = (new_id(p) for p in ("vch", "vcv"))
        shc = new_id("shc")
        setv, rsnap, rsin = (new_id(p) for p in ("setv", "rsnap", "rsin"))

        conn.execute(
            "INSERT INTO finding (id, brand_id, campaign_cycle_id, finding_type, severity, code,"
            " message, confidence_penalty, source, created_at) VALUES"
            " (?, ?, ?, 'compliance', 'warn', 'x', '測試', 0, 'rule_scan', ?)",
            (fnd, self.bid, cycle_id, ts),
        )
        conn.execute(
            "INSERT INTO interrupt (id, brand_id, campaign_cycle_id, dedupe_key, category,"
            " severity, message, status, created_at) VALUES"
            " (?, ?, ?, ?, 'cycle_reminder', 'informational', '測試提醒訊息', 'open', ?)",
            (rmd, self.bid, cycle_id, f"cycle_reminder:{cycle_id}:test", ts),
        )
        conn.execute(
            "INSERT INTO campaign_plan_option (id, campaign_cycle_id, brand_id, option_index,"
            " option_json, created_at) VALUES (?, ?, ?, 0, '{}', ?)",
            (cpo, cycle_id, self.bid, ts),
        )
        cpl = new_id("cpl")
        conn.execute(
            "INSERT INTO campaign_plan (id, campaign_cycle_id, brand_id, plan_version, plan_json,"
            " status, created_at) VALUES (?, ?, ?, 1, '{}', 'approved', ?)",
            (cpl, cycle_id, self.bid, ts),
        )
        gol = new_id("gol")
        conn.execute(
            "INSERT INTO marketing_goal (id, brand_id, objective_summary, status, created_at,"
            " updated_at) VALUES (?, ?, '測試目標', 'active', ?, ?)",
            (gol, self.bid, ts, ts),
        )
        conn.execute(
            "INSERT INTO campaign_cycle_goal (campaign_cycle_id, goal_id, brand_id, rank)"
            " VALUES (?, ?, ?, 1)",
            (cycle_id, gol, self.bid),
        )
        conn.execute(
            "INSERT INTO campaign_cycle_hypothesis (campaign_cycle_id, strategy_hypothesis_id,"
            " brand_id, role) VALUES (?, 'hyp_fake_test', ?, 'audience')",
            (cycle_id, self.bid),
        )
        conn.execute(
            "INSERT INTO rule_dissent (id, brand_id, campaign_cycle_id, target_type, suggestion,"
            " reason, status, created_at) VALUES"
            " (?, ?, ?, 'offer', '測試建議', '測試理由', 'pending', ?)",
            (dsn, self.bid, cycle_id, ts),
        )
        conn.execute(
            "INSERT INTO cycle_checkpoint (id, brand_id, campaign_cycle_id, kind, result_json,"
            " status, created_at, updated_at) VALUES (?, ?, ?, 'day3', '{}', 'active', ?, ?)",
            (chk, self.bid, cycle_id, ts, ts),
        )
        conn.execute(
            "INSERT INTO cycle_checklist_item (id, brand_id, campaign_cycle_id, item_key, checked,"
            " updated_at) VALUES (?, ?, ?, 'test_item', 1, ?)",
            (ccl, self.bid, cycle_id, ts),
        )
        conn.execute(
            "INSERT INTO experiment_cell (id, campaign_cycle_id, brand_id, created_at)"
            " VALUES (?, ?, ?, ?)",
            (exc, cycle_id, self.bid, ts),
        )
        conn.execute(
            "INSERT INTO creative_brief (id, campaign_cycle_id, experiment_cell_id, brand_id,"
            " brief_type, purpose, status, created_at, updated_at) VALUES"
            " (?, ?, ?, ?, 'copy', '測試', 'draft', ?, ?)",
            (cbf, cycle_id, exc, self.bid, ts, ts),
        )
        conn.execute(
            "INSERT INTO creative_variant (id, variant_type, creative_brief_id, campaign_cycle_id,"
            " experiment_cell_id, brand_id, attributes_json, status, created_at) VALUES"
            " (?, 'copy', ?, ?, ?, ?, '{}', 'DRAFT', ?)",
            (cvr, cbf, cycle_id, exc, self.bid, ts),
        )
        conn.execute(
            "INSERT INTO adoption_decision (id, brand_id, campaign_cycle_id, target_type, target_id,"
            " decision, decided_by, decided_at) VALUES"
            " (?, ?, ?, 'variant', ?, 'adopted', ?, ?)",
            (adp, self.bid, cycle_id, cvr, ACTOR, ts),
        )
        conn.execute(
            "INSERT INTO final_asset (id, brand_id, campaign_cycle_id, source_variant_id,"
            " asset_type, file_path, status, created_at, updated_at) VALUES"
            " (?, ?, ?, ?, 'image', 'C:/tmp/x.png', 'DRAFT', ?, ?)",
            (fas, self.bid, cycle_id, cvr, ts, ts),
        )
        conn.execute(
            "INSERT INTO publishing_package (id, brand_id, campaign_cycle_id, experiment_cell_id,"
            " final_asset_id, hook_id, campaign_name, adset_name, ad_name, destination_url,"
            " utm_json, status, created_at) VALUES"
            " (?, ?, ?, ?, ?, ?, '測試檔期', '測試組', '測試廣告',"
            " 'https://example.com', '{}', 'draft', ?)",
            (pkg, self.bid, cycle_id, exc, fas, cvr, ts),
        )
        conn.execute(
            "INSERT INTO external_ad_mapping (id, brand_id, publishing_package_id,"
            " campaign_cycle_id, platform, internal_asset_id, claim_status, created_at) VALUES"
            " (?, ?, ?, ?, 'meta', ?, 'confirmed', ?)",
            (xam, self.bid, pkg, cycle_id, fas, ts),
        )
        conn.execute(
            "INSERT INTO activation_authorization (id, brand_id, scope_type, scope_ref,"
            " authorized_by, authorized_at, created_at) VALUES"
            " (?, ?, 'campaign_activation', ?, ?, ?, ?)",
            (ath, self.bid, cycle_id, ACTOR, ts, ts),
        )
        conn.execute(
            "INSERT INTO campaign_activation (id, brand_id, campaign_cycle_id,"
            " external_ad_mapping_id, authorization_id, activated_by, activated_at, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (act, self.bid, cycle_id, xam, ath, ACTOR, ts, ts),
        )
        conn.execute(
            "INSERT INTO performance_snapshot (id, brand_id, campaign_cycle_id,"
            " external_ad_mapping_id, platform, date_range_start, date_range_end, as_of_date,"
            " snapshot_taken_at, currency, source, created_at) VALUES"
            " (?, ?, ?, ?, 'meta', '2026-01-01', '2026-01-01', '2026-01-01', ?,"
            " 'TWD', 'manual', ?)",
            (psn, self.bid, cycle_id, xam, ts, ts),
        )
        conn.execute(
            "INSERT INTO derived_metric (id, brand_id, performance_snapshot_id,"
            " campaign_cycle_id, external_ad_mapping_id, metric, value, computed_at, created_at)"
            " VALUES (?, ?, ?, ?, ?, 'ctr', 1.0, ?, ?)",
            (dmt, self.bid, psn, cycle_id, xam, ts, ts),
        )
        conn.execute(
            "INSERT INTO performance_reading (id, brand_id, campaign_cycle_id,"
            " experiment_cell_id, external_ad_mapping_id, status, rule_result_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, 'learning', '{}', ?)",
            (prd, self.bid, cycle_id, exc, xam, ts),
        )
        conn.execute(
            "INSERT INTO recommendation (id, brand_id, campaign_cycle_id,"
            " performance_reading_id, recommendation_type, content_json, status, created_at,"
            " updated_at) VALUES (?, ?, ?, ?, 'maintain', '{}', 'DRAFT', ?, ?)",
            (rec, self.bid, cycle_id, prd, ts, ts),
        )
        conn.execute(
            "INSERT INTO cycle_voucher_code (id, brand_id, campaign_cycle_id, source_type, code,"
            " discount_type, discount_value, usage_limit, valid_from, valid_to, created_at,"
            " updated_at) VALUES (?, ?, ?, 'ad', 'TESTCODE', 'percent', 10, 50, '2026-01-01',"
            " '2026-01-14', ?, ?)",
            (vch, self.bid, cycle_id, ts, ts),
        )
        conn.execute(
            "INSERT INTO cycle_code_verification (id, brand_id, campaign_cycle_id, passed,"
            " checked_by, checked_at, created_at) VALUES (?, ?, ?, 1, ?, ?, ?)",
            (vcv, self.bid, cycle_id, ACTOR, ts, ts),
        )
        conn.execute(
            "INSERT INTO cycle_shopee_code (id, brand_id, campaign_cycle_id, code,"
            " redemption_count, updated_by, created_at, updated_at) VALUES"
            " (?, ?, ?, 'SHOPTEST', 1, ?, ?, ?)",
            (shc, self.bid, cycle_id, ACTOR, ts, ts),
        )
        conn.execute(
            "INSERT INTO settlement_version (id, brand_id, campaign_cycle_id, version,"
            " trigger_reason, is_post_close, created_by, created_at) VALUES"
            " (?, ?, ?, 1, 'initial', 0, ?, ?)",
            (setv, self.bid, cycle_id, ACTOR, ts),
        )
        conn.execute(
            "INSERT INTO reading_snapshot (id, brand_id, campaign_cycle_id,"
            " settlement_version_id, coefficient_version_id, data_arrival_json,"
            " missing_sources_json, summary_json, created_at) VALUES"
            " (?, ?, ?, ?, NULL, '{}', '[]', '{}', ?)",
            (rsnap, self.bid, cycle_id, setv, ts),
        )
        conn.execute(
            "INSERT INTO reading_snapshot_input (id, brand_id, campaign_cycle_id,"
            " reading_snapshot_id, scope, key, value, created_at) VALUES"
            " (?, ?, ?, ?, 'cycle', 'spend', '100', ?)",
            (rsin, self.bid, cycle_id, rsnap, ts),
        )
        conn.execute(
            "INSERT INTO learning_ledger (id, brand_id, learning_text, applicability_scope,"
            " source_cycle_id, source_reading_id, learned_at, created_by, created_at) VALUES"
            " (?, ?, '測試學習：這招有用', 'brand', ?, ?, ?, ?, ?)",
            (lrn, self.bid, cycle_id, prd, ts, ACTOR, ts),
        )
        conn.commit()
        return {"learning_ledger_id": lrn}

    _CASCADE_TABLES = [t for t, _label in ads_repo.CYCLE_CASCADE_TABLES]

    def _cascade_row_counts(self, cycle_id):
        return {t: main.conn.execute(
            f"SELECT COUNT(*) FROM {t} WHERE campaign_cycle_id = ?", (cycle_id,)
        ).fetchone()[0] for t in self._CASCADE_TABLES}


class RepositoryCascadeDeleteTest(_BaseCycleDeleteTest):
    def test_active_cycle_cannot_be_deleted(self):
        cycle_id = self._open_cycle()
        with self.assertRaises(ValueError):
            ads_repo.delete_cycle(main.conn, self.bid, cycle_id, actor=ACTOR)
        self.assertIsNotNone(ads_repo.get_cycle(main.conn, self.bid, cycle_id))

    def test_archived_cycle_is_wiped_from_every_cascade_table_no_orphans(self):
        cycle_id = self._open_cycle()
        self._seed_cascade_rows(cycle_id)
        self.assertTrue(all(n > 0 for n in self._cascade_row_counts(cycle_id).values()),
                        self._cascade_row_counts(cycle_id))

        ads_repo.set_cycle_archived(main.conn, self.bid, cycle_id, archived=True, actor=ACTOR)
        ads_repo.delete_cycle(main.conn, self.bid, cycle_id, actor=ACTOR)

        self.assertIsNone(ads_repo.get_cycle(main.conn, self.bid, cycle_id))
        self.assertEqual(set(self._cascade_row_counts(cycle_id).values()), {0})

    def test_learning_ledger_survives_but_detaches_from_deleted_cycle(self):
        """學習紀錄是跨期累積的資產，來源檔期被刪不代表學習作廢——只解除關聯，不刪列。"""
        cycle_id = self._open_cycle()
        seeded = self._seed_cascade_rows(cycle_id)

        ads_repo.set_cycle_archived(main.conn, self.bid, cycle_id, archived=True, actor=ACTOR)
        ads_repo.delete_cycle(main.conn, self.bid, cycle_id, actor=ACTOR)

        row = main.conn.execute(
            "SELECT * FROM learning_ledger WHERE id = ?",
            (seeded["learning_ledger_id"],)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["learning_text"], "測試學習：這招有用")
        self.assertIsNone(row["source_cycle_id"])
        self.assertIsNone(row["source_reading_id"])

    def test_delete_leaves_audit_trail_with_counts(self):
        cycle_id = self._open_cycle()
        self._seed_cascade_rows(cycle_id)
        label = self._cycle_label(cycle_id)

        ads_repo.set_cycle_archived(main.conn, self.bid, cycle_id, archived=True, actor=ACTOR)
        ads_repo.delete_cycle(main.conn, self.bid, cycle_id, actor=ACTOR)

        row = main.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'campaign_cycle' AND action = 'delete' "
            "AND entity_id = ?", (cycle_id,)).fetchone()
        self.assertIsNotNone(row)
        before = json.loads(row["before_json"])
        self.assertEqual(before["start_date"] + " ～ " + before["end_date"], label)
        self.assertGreater(before["deleted_counts"]["成效判讀"], 0)
        self.assertEqual(row["actor"], ACTOR)

    def test_archive_and_restore_round_trip_any_status(self):
        """任何狀態（含 LIVE、CLOSED）都能封存／還原。"""
        cycle_id = self._open_cycle()
        ads_repo.update_cycle_status(main.conn, self.bid, cycle_id, status="LIVE", actor=ACTOR)

        archived = ads_repo.set_cycle_archived(main.conn, self.bid, cycle_id, archived=True,
                                               actor=ACTOR)
        self.assertEqual(archived["archived"], 1)
        self.assertEqual(archived["status"], "LIVE")

        restored = ads_repo.set_cycle_archived(main.conn, self.bid, cycle_id, archived=False,
                                               actor=ACTOR)
        self.assertEqual(restored["archived"], 0)

    def test_other_cycle_rows_untouched(self):
        gone = self._open_cycle()
        kept = self._open_cycle()
        self._seed_cascade_rows(gone)
        before_kept_count = ads_repo.get_cycle(main.conn, self.bid, kept)
        self.assertIsNotNone(before_kept_count)

        ads_repo.set_cycle_archived(main.conn, self.bid, gone, archived=True, actor=ACTOR)
        ads_repo.delete_cycle(main.conn, self.bid, gone, actor=ACTOR)

        self.assertIsNotNone(ads_repo.get_cycle(main.conn, self.bid, kept))


class CycleArchiveRestoreRouteTest(_BaseCycleDeleteTest):
    def test_archive_then_restore_via_route(self):
        cycle_id = self._open_cycle()
        resp = self.client.post(f"/brands/{self.bid}/ads/{cycle_id}/archive",
                                follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(ads_repo.get_cycle(main.conn, self.bid, cycle_id)["archived"], 1)

        self.client.post(f"/brands/{self.bid}/ads/{cycle_id}/archive", follow_redirects=False)
        self.assertEqual(ads_repo.get_cycle(main.conn, self.bid, cycle_id)["archived"], 0)

    def test_archived_cycle_hidden_from_default_list_shown_when_toggled(self):
        """D線票3（#45）：封存收合區從廣告首頁搬到 /ads/history（hub 只留五張卡，
        不再列全部檔期），這裡改看歷期戰績頁，收合區行為（預設不顯示、可切換）不變。"""
        cycle_id = self._open_cycle()
        label = self._cycle_label(cycle_id)
        self.client.post(f"/brands/{self.bid}/ads/{cycle_id}/archive", follow_redirects=False)

        history = self.client.get(f"/brands/{self.bid}/ads/history")
        self.assertIn("已封存檔期", history.text)
        self.assertIn(label, history.text)  # 出現在收合區塊裡

    def test_active_cycle_still_shown_when_not_archived(self):
        """D線票3（#45）：檔期清單搬到 /ads/history，這裡改看歷期戰績頁。"""
        cycle_id = self._open_cycle()
        label = self._cycle_label(cycle_id)
        history = self.client.get(f"/brands/{self.bid}/ads/history")
        self.assertIn(label, history.text)


class CycleDeleteRouteTest(_BaseCycleDeleteTest):
    def test_delete_page_blocked_while_active(self):
        cycle_id = self._open_cycle()
        resp = self.client.get(f"/brands/{self.bid}/ads/{cycle_id}/delete",
                               follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertNotIn("/delete", resp.headers["location"])

        resp = self.client.post(f"/brands/{self.bid}/ads/{cycle_id}/delete",
                                data={"confirm_name": "亂打"}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertIsNotNone(ads_repo.get_cycle(main.conn, self.bid, cycle_id))

    def test_wrong_name_does_not_delete(self):
        cycle_id = self._open_cycle()
        self.client.post(f"/brands/{self.bid}/ads/{cycle_id}/archive", follow_redirects=False)

        resp = self.client.post(f"/brands/{self.bid}/ads/{cycle_id}/delete",
                                data={"confirm_name": "打錯了"}, follow_redirects=False)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("跟上面顯示的不一樣", resp.text)
        self.assertIsNotNone(ads_repo.get_cycle(main.conn, self.bid, cycle_id))

    def test_delete_page_lists_connected_data(self):
        cycle_id = self._open_cycle()
        self._seed_cascade_rows(cycle_id)
        self.client.post(f"/brands/{self.bid}/ads/{cycle_id}/archive", follow_redirects=False)

        page = self.client.get(f"/brands/{self.bid}/ads/{cycle_id}/delete")
        self.assertEqual(page.status_code, 200)
        self.assertIn("成效判讀", page.text)
        self.assertIn("廣告素材", page.text)

    def test_correct_name_deletes_and_snapshots_backup_no_orphans(self):
        cycle_id = self._open_cycle()
        self._seed_cascade_rows(cycle_id)
        label = self._cycle_label(cycle_id)
        self.client.post(f"/brands/{self.bid}/ads/{cycle_id}/archive", follow_redirects=False)

        backup_dir = Path(os.environ["BRAND_OS_BACKUP_DIR"])
        before_snapshots = list(backup_dir.glob(f"before-delete-{cycle_id}-*.db")) \
            if backup_dir.exists() else []
        self.assertEqual(before_snapshots, [])

        resp = self.client.post(f"/brands/{self.bid}/ads/{cycle_id}/delete",
                                data={"confirm_name": label}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertIsNone(ads_repo.get_cycle(main.conn, self.bid, cycle_id))
        self.assertEqual(set(self._cascade_row_counts(cycle_id).values()), {0})

        after_snapshots = list(backup_dir.glob(f"before-delete-{cycle_id}-*.db"))
        self.assertEqual(len(after_snapshots), 1)

        row = main.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'campaign_cycle' AND action = 'delete' "
            "AND entity_id = ?", (cycle_id,)).fetchone()
        self.assertIsNotNone(row)


if __name__ == "__main__":
    unittest.main()
