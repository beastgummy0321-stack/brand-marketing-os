"""app/tests/test_workbench_looks.py — F07-I04 (ARCHITECTURE.md §5.9): the program-only slot
plan (`looks.allocate`/`looks.recommend`/`looks.plan_text`), the learnings read
(`looks.visual_learnings`) and the two repository reads it is built on
(`repository.look_history`/`repository.image_round_history`).
"""

import random
import unittest
import uuid
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.brand_intelligence import repository as bi_repo
from app.core import db
from app.workbench import encode_learning_scope, looks
from app.workbench import repository as workbench_repo

ACTOR = "測試員"


class CoordinateVocabularyReadTest(unittest.TestCase):
    def test_shared_read_preserves_scope_order_shape_and_does_not_seed(self):
        conn = db.current()
        brand = bi_repo.create_brand(conn, name="Vocabulary", client_name=None,
                                     actor=ACTOR, org_id=db.DEV_ORG_ID)["id"]
        other = bi_repo.create_brand(conn, name="Other vocabulary", client_name=None,
                                     actor=ACTOR, org_id=db.DEV_ORG_ID)["id"]
        conn.commit()
        self.assertEqual(workbench_repo.list_coordinate_vocabulary(conn, db.DEV_ORG_ID, brand), [])
        self.assertEqual(looks.current_conditions(conn, db.DEV_ORG_ID, brand, None)[
            "audience_keys"], [])
        client = TestClient(main.app)

        def create(brand_id, dimension, label, category):
            response = client.post(f"/api/schedule/brands/{brand_id}/coordinates", json={
                "dimension": dimension, "label": label, "category": category,
            })
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        last = create(brand, "audience", "A without category", "")
        second = create(brand, "audience", "Z in category", "A")
        first = create(brand, "audience", "B in category", "A")
        angle = create(brand, "angle", "Angle", "")
        foreign = create(other, "audience", "Foreign", "")
        disabled = client.post(
            f"/api/schedule/brands/{brand}/coordinates/{second['id']}/disable",
            json={"disabled": True},
        )
        self.assertEqual(disabled.status_code, 200, disabled.text)
        rows = workbench_repo.list_coordinate_vocabulary(conn, db.DEV_ORG_ID, brand)
        self.assertEqual([r["key"] for r in rows],
                         [angle["key"], first["key"], second["key"], last["key"]])
        self.assertEqual(set(rows[0]), {
            "dimension", "key", "label", "attributes", "disabled_at", "rejected",
        })
        self.assertEqual(rows[0]["attributes"], {})
        self.assertFalse(rows[0]["rejected"])
        self.assertIsNotNone(rows[2]["disabled_at"])
        current = looks.current_conditions(conn, db.DEV_ORG_ID, brand, None)
        self.assertEqual(current["audience_keys"],
                         [first["key"], second["key"], last["key"]])
        self.assertNotIn(foreign["key"], current["audience_keys"])
        self.assertEqual(workbench_repo.list_coordinate_vocabulary(conn, "other-org", brand), [])
        self.assertEqual(looks.current_conditions(conn, "other-org", brand, None)[
            "audience_keys"], [])
        self.assertIsNone(current["result_kind"])
        self.assertIsNone(current["conditions"]["target_version"])


class AllocateTest(unittest.TestCase):
    def test_cold_start_no_winners_no_history(self):
        fit = ["clean_bright", "editorial_portrait", "documentary", "soft_lifestyle"]
        result = looks.allocate(
            10, fit_looks=fit, excluded=[], winners=[], history={},
            rng=random.Random(1),
        )
        exploit_counts = {}
        for look, slot in result["plan"]:
            if slot == "exploit":
                exploit_counts[look] = exploit_counts.get(look, 0) + 1
        self.assertEqual(exploit_counts, {
            "clean_bright": 2, "editorial_portrait": 2, "documentary": 2, "soft_lifestyle": 1,
        })
        explore_looks = [look for look, slot in result["plan"] if slot == "explore"]
        self.assertEqual(set(explore_looks), {"phone_raw", "flash_snapshot", "studio_hero"})
        self.assertEqual(len(explore_looks), 3)
        self.assertEqual(result["explore_first"], "phone_raw")
        self.assertEqual(result["exploit_looks"], fit)
        self.assertEqual(result["explore_looks"], ["phone_raw", "flash_snapshot", "studio_hero"])

    def test_winners_and_history_change_exploit_and_explore_order(self):
        result = looks.allocate(
            10,
            fit_looks=["soft_lifestyle", "clean_bright", "documentary", "studio_hero"],
            excluded=[], winners=["soft_lifestyle"],
            history={
                "documentary": {"adopted": 2, "offered": 2},
                "clean_bright": {"adopted": 1, "offered": 1},
            },
            rng=random.Random(2),
        )
        exploit_looks_used = {look for look, slot in result["plan"] if slot == "exploit"}
        self.assertEqual(exploit_looks_used, {"soft_lifestyle"})
        self.assertEqual(
            sum(1 for look, slot in result["plan"] if slot == "exploit"), 7,
        )
        self.assertEqual(result["explore_first"], "studio_hero")
        self.assertEqual(result["explore_looks"], ["studio_hero", "phone_raw", "flash_snapshot"])

    def test_excluded_never_appears_even_as_winner(self):
        result = looks.allocate(
            10, fit_looks=["clean_bright", "documentary", "soft_lifestyle", "phone_raw"],
            excluded=["phone_raw"], winners=["phone_raw"], history={},
            rng=random.Random(3),
        )
        used = {look for look, _slot in result["plan"]}
        self.assertNotIn("phone_raw", used)

    def test_brand_spec_first_in_fit_is_never_excluded(self):
        fit = [looks.BRAND_SPEC, "clean_bright", "documentary", "soft_lifestyle"]
        result = looks.allocate(
            10, fit_looks=fit, excluded=[looks.BRAND_SPEC], winners=[], history={},
            rng=random.Random(4),
        )
        self.assertIn(looks.BRAND_SPEC, result["exploit_looks"])

    def test_offered_spreads_exploration_across_rounds(self):
        fit = ["clean_bright", "editorial_portrait", "documentary", "soft_lifestyle"]
        round1 = looks.allocate(
            10, fit_looks=fit, excluded=[], winners=[], history={}, rng=random.Random(5),
        )
        history2 = {
            look: {"adopted": 0, "offered": 1} for look in round1["explore_looks"]
        }
        round2 = looks.allocate(
            10, fit_looks=fit, excluded=[], winners=[], history=history2,
            rng=random.Random(6),
        )
        self.assertEqual(set(round1["explore_looks"]) & set(round2["explore_looks"]), set())

    def test_n_2_carousel_not_shuffled_explore_outside_pool(self):
        fit = ["clean_bright", "editorial_portrait"]
        seed = None
        for s in range(100):
            lst = [0, 1]
            random.Random(s).shuffle(lst)
            if lst == [1, 0]:
                seed = s
                break
        result = looks.allocate(
            2, fit_looks=fit, excluded=[], winners=[], history={}, rng=random.Random(seed),
        )
        self.assertEqual(
            result["plan"], [("clean_bright", "exploit"), ("phone_raw", "explore")],
        )
        self.assertEqual(result["explore_first"], "phone_raw")

    def test_cold_start_with_brand_spec_plan_text_stable_across_seeds(self):
        fit = [looks.BRAND_SPEC, "clean_bright", "documentary", "soft_lifestyle"]
        r1 = looks.allocate(
            10, fit_looks=fit, excluded=[], winners=[], history={}, rng=random.Random(11),
        )
        r2 = looks.allocate(
            10, fit_looks=fit, excluded=[], winners=[], history={}, rng=random.Random(99),
        )
        text1 = looks.plan_text(r1["exploit_looks"], r1["explore_looks"])
        text2 = looks.plan_text(r2["exploit_looks"], r2["explore_looks"])
        self.assertEqual(text1, text2)
        self.assertTrue(text1.startswith("主力：品牌規範、"))
        # slot order differs between the two rng seeds even though the summary text matches
        self.assertNotEqual(r1["plan"], r2["plan"])


class RecommendTest(unittest.TestCase):
    def test_ten_consecutive_rounds_recommend_explore_three_times(self):
        fit = ["clean_bright", "editorial_portrait", "documentary", "soft_lifestyle"]
        rounds = 0
        explore_recommended = 0
        explore_count = 0
        for seed in range(10):
            result = looks.allocate(
                10, fit_looks=fit, excluded=[], winners=[], history={},
                rng=random.Random(seed),
            )
            index = looks.recommend(
                result["plan"], result["explore_first"],
                rounds=rounds, explore_recommended=explore_recommended,
            )
            recommended_slot = result["plan"][index - 1][1]
            if recommended_slot == "explore":
                explore_count += 1
                explore_recommended += 1
            rounds += 1
        self.assertEqual(explore_count, 3)

    def test_recommendation_lands_on_designated_explore_look(self):
        plan = [
            ("flash_snapshot", "explore"), ("clean_bright", "exploit"),
            ("phone_raw", "explore"),
        ]
        index = looks.recommend(
            plan, "phone_raw", rounds=9, explore_recommended=0,
        )
        self.assertEqual(index, 3)

    def test_no_explore_slot_falls_back_to_exploit_even_when_ratio_allows(self):
        plan = [("clean_bright", "exploit"), ("phone_raw", "exploit")]
        index = looks.recommend(
            plan, "phone_raw", rounds=9, explore_recommended=0,
        )
        self.assertEqual(index, 1)


class VisualLearningsTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.brand_id = bi_repo.create_brand(
            self.conn, name="視覺學習測試品牌", client_name=None, actor=ACTOR,
            org_id=db.DEV_ORG_ID,
        )["id"]
        self.product = bi_repo.create_product(self.conn, self.brand_id, name="Product", actor=ACTOR)
        self.current = {"org_id": db.DEV_ORG_ID, "brand_id": self.brand_id,
                        "product_id": self.product["id"], "org_day": date.today().isoformat(),
                        "result_kind": "purchase", "currency": "TWD", "attribution": "7d",
                        "mode": "real", "audience_keys": ["warm_engaged", "cold_unaware"],
                        "customer_group_ids": [], "conditions": {
                            "price_version": "price", "target_version": "target",
                            "offers": [], "materials": [],
                        }}

    def _view(self, audience, *, today):
        return looks.visual_learnings(self.conn, self.brand_id, audience, today=today,
                                      product_id=self.product["id"], current=self.current,
                                      min_result_events=10)

    def _learning(self, *, text, scope, confidence, days_ago=0, source_track="visual",
                  result_events=10):
        end = date.today() - timedelta(days=days_ago)
        evidence = {"schema_version": 1, "source_kind": "visual",
                    "provenance": "platform_observation",
                    "source_version": "retained", "direction": "support",
                    "scope": {"product_id": self.product["id"], "audience_key": scope.split("；")[1]
                              .removeprefix("audience=") if "；" in scope else None,
                              "claim_key": scope, "claim_family": "performance",
                              "objective_family": "sales", "result_kind": "purchase",
                              "currency": "TWD", "attribution": "7d"},
                    "conditions": {"price_version": "price", "target_version": "target",
                                   "offer_key": "none"}, "sample": {"result_events": result_events}}

        def write(day):
            return bi_repo.record_learning(
                self.conn, self.brand_id, actor=ACTOR, learning_text=text,
                product_id=self.product["id"],
                applicability_scope=encode_learning_scope(scope, {**evidence,
                    "source_ref": {"trial_id": str(uuid.uuid4())},
                    "period": {"start": day.isoformat(), "end": day.isoformat()}}),
                confidence=confidence, sample_size="3", source_track=source_track,
                learned_at=datetime.now(UTC) - timedelta(days=(date.today() - day).days),
            )

        if confidence in ("likely", "validated"):
            write(end - timedelta(days=1))
        return write(end)

    def test_request_threshold_never_promotes_one_event_or_changes_the_policy(self):
        self._learning(text="One event per trial", confidence="validated", result_events=1,
                       scope="visual；audience=warm_engaged；look=soft_lifestyle")
        for value in (1, None, "invalid"):
            with self.subTest(requested=value):
                result = looks.visual_learnings(
                    self.conn, self.brand_id, "warm_engaged", today=date.today(),
                    product_id=self.product["id"], current=self.current, min_result_events=value,
                )
                self.assertEqual(result["winners"], [])
                self.assertTrue(all("market_support" not in row["allowed_uses"]
                                    for row in result["evidence_context"]["items"]))

    def test_queued_ads_snapshot_is_historical_and_product_mismatch_is_excluded(self):
        row = self._learning(text="Retained old winner", confidence="validated",
                             scope="visual；audience=warm_engaged；look=soft_lifestyle")
        creative = {"input_hash": "accepted-original", "assignment": {"offer_key": "none"},
                    "comparison": {"learning_current": self.current,
                                   "learning_min_result_events": 1,
                                   "learnings": [{"id": row["id"], "text": "Retained old winner"}],
                                   "controls": [{"creative": {"copy_fields": {"body": "Exact"}}}]}}
        original = deepcopy(creative)
        with patch.object(looks.settings, "today_for_org", return_value=date.today()):
            current = looks.current_conditions(self.conn, db.DEV_ORG_ID, self.brand_id,
                                               self.product["id"], supplied=self.current)
            self.assertIsNone(current["conditions"]["target_version"])
            self.assertEqual(current["conditions"]["materials"], [])
            self.assertIsNone(current["result_kind"])
            result = looks.qualified_creative(self.conn, db.DEV_ORG_ID, self.brand_id,
                                              self.product["id"], creative)
            other = bi_repo.create_product(self.conn, self.brand_id, name="Other", actor=ACTOR)
            mismatch = looks.qualified_creative(self.conn, db.DEV_ORG_ID, self.brand_id,
                                                other["id"], creative)
        for output in (result, mismatch):
            self.assertEqual(output["input_hash"], "accepted-original")
            self.assertEqual(output["comparison"]["controls"], original["comparison"]["controls"])
            self.assertNotIn("market_support", output["comparison"]["learnings"][0][
                "evidence"]["allowed_uses"])
        self.assertEqual(mismatch["comparison"]["learnings"][0]["evidence"]["use_state"],
                         "excluded")
        self.assertEqual(creative, original)

    def test_matches_filtered_by_confidence_scope_age_and_track(self):
        today = date.today()
        r_likely = self._learning(
            text="likely 命中", scope="visual；audience=warm_engaged；look=soft_lifestyle",
            confidence="likely",
        )
        r_validated = self._learning(
            text="validated 命中",
            scope="visual；audience=warm_engaged；device=contrast", confidence="validated",
        )
        self._learning(
            text="observed 不算數", scope="visual；audience=warm_engaged；look=studio_hero",
            confidence="observed",
        )
        self._learning(
            text="看不出不算數", scope="visual；audience=warm_engaged；look=看不出",
            confidence="likely",
        )
        self._learning(
            text="別的受眾不算數", scope="visual；audience=cold_unaware；look=dark_luxury",
            confidence="likely",
        )
        self._learning(
            text="過期不算數", scope="visual；audience=warm_engaged；look=cinematic",
            confidence="likely", days_ago=200,
        )
        self._learning(
            text="ads 軌不算數", scope="visual；audience=warm_engaged；look=bold_graphic",
            confidence="likely", source_track="ads",
        )

        result = self._view("warm_engaged", today=today)
        self.assertEqual({line.split("（")[0] for line in result["lines"]},
                         {"likely 命中", "validated 命中"})
        self.assertEqual(result["omitted"], 0)
        self.assertEqual(result["winners"], ["soft_lifestyle"])
        self.assertIn(r_likely["id"], result["ids"])
        self.assertIn(r_validated["id"], result["ids"])

    def test_more_than_five_matches_truncates_and_counts_omitted(self):
        today = date.today()
        for i in range(6):
            self._learning(
                text=f"命中第{i}條", scope=f"visual；audience=warm_engaged；device=d{i}",
                confidence="likely",
            )
        result = self._view("warm_engaged", today=today)
        self.assertEqual(len(result["lines"]), 5)
        self.assertEqual(result["omitted"], 1)

    def test_none_audience_returns_empty(self):
        self._learning(
            text="不該出現", scope="visual；audience=warm_engaged；look=soft_lifestyle",
            confidence="likely",
        )
        result = looks.visual_learnings(self.conn, self.brand_id, None, today=date.today())
        self.assertEqual(result, {"winners": [], "lines": [], "omitted": 0, "ids": []})

    def test_expired_learnings_excluded(self):
        today = date.today()
        row = self._learning(
            text="快要過期", scope="visual；audience=warm_engaged；look=documentary",
            confidence="likely",
        )
        bi_repo.expire_learning(self.conn, self.brand_id, row["id"], actor=ACTOR)
        result = self._view("warm_engaged", today=today)
        self.assertNotIn(row["learning_text"], result["lines"])
        self.assertNotIn(row["id"], result["ids"])

    def test_newer_winners_first(self):
        today = date.today()
        self._learning(
            text="cinematic 較舊", scope="visual；audience=warm_engaged；look=cinematic",
            confidence="likely", days_ago=10,
        )
        self._learning(
            text="documentary 較新", scope="visual；audience=warm_engaged；look=documentary",
            confidence="likely", days_ago=1,
        )
        result = self._view("warm_engaged", today=today)
        self.assertEqual(result["winners"], ["documentary", "cinematic"])
        self.assertEqual([line.split("（")[0] for line in result["lines"]],
                         ["documentary 較新", "cinematic 較舊"])

    def test_malformed_scopes_skipped_without_error(self):
        today = date.today()
        self._learning(
            text="缺 audience 段", scope="visual；look=phone_raw", confidence="likely",
        )
        self._learning(
            text="缺維度段", scope="visual；audience=warm_engaged", confidence="likely",
        )
        self._learning(
            text="維度段格式錯", scope="visual；audience=warm_engaged；broken",
            confidence="likely",
        )
        result = self._view("warm_engaged", today=today)
        self.assertEqual(result["lines"], [])

    def test_winner_id_beyond_the_five_lines_still_collected(self):
        today = date.today()
        oldest = self._learning(
            text="第 6 條（最舊，look 列）",
            scope="visual；audience=warm_engaged；look=dark_luxury",
            confidence="likely", days_ago=6,
        )
        for i in range(5):
            self._learning(
                text=f"命中第{i}條", scope=f"visual；audience=warm_engaged；device=d{i}",
                confidence="likely", days_ago=i,
            )
        result = self._view("warm_engaged", today=today)
        self.assertNotIn(oldest["learning_text"], result["lines"])
        self.assertIn("dark_luxury", result["winners"])
        self.assertIn(oldest["id"], result["ids"])


class RepositoryHistoryTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.org_id = db.DEV_ORG_ID
        self.brand_id = bi_repo.create_brand(
            self.conn, org_id=self.org_id, name="風格歷史測試品牌", client_name=None,
            actor=ACTOR,
        )["id"]

    def _submit_set(self) -> str:
        pack = {
            "source_kind": "schedule_node",
            "source_ref": {"source_tree_task_id": str(uuid.uuid4())},
            "name": "測試任務包",
            "sets": [{
                "name": "單元 1", "source_ref": {"node_key": "1"}, "coordinates": {},
                "style_key": "ugc", "required_outputs": {"image_prompt": 1},
                "request": {"image_prompt_count": 1},
            }],
        }
        pack_id = workbench_repo.submit_pack(self.conn, self.org_id, self.brand_id, pack)
        rows = self.conn.execute(
            "SELECT id FROM workbench_brief WHERE org_id = %s AND brand_id = %s"
            " AND pack_id = %s ORDER BY created_at",
            (self.org_id, self.brand_id, pack_id),
        ).fetchall()
        return rows[0]["id"]

    def _write_round(self, brief_id: str, *, round_num: int, look: str,
                      audience_key: str | None, recommended_slot: str) -> dict:
        return workbench_repo.write_output(
            self.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief_id,
            part="image_prompt", generation_round=round_num,
            body_json={
                "fingerprint": {"look": {"key": look, "label": looks.look_label(look)}},
                "round": {
                    "audience_key": audience_key, "recommended_slot": recommended_slot,
                },
            },
            coordinates_json=None, llm_task_id=None,
        )

    def test_look_history_and_image_round_history(self):
        brief_id = self._submit_set()
        out1 = self._write_round(
            brief_id, round_num=1, look="soft_lifestyle",
            audience_key="warm_engaged", recommended_slot="exploit",
        )
        self._write_round(
            brief_id, round_num=2, look="soft_lifestyle",
            audience_key="warm_engaged", recommended_slot="explore",
        )
        workbench_repo.adopt_output(self.conn, self.org_id, self.brand_id, out1["id"])
        # a multi-version round (輪播): both versions carry `round`, only version_index 1 counts
        workbench_repo.write_output(
            self.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief_id,
            part="image_prompt", generation_round=3,
            body_json=[
                {
                    "fingerprint": {"look": {"key": "documentary", "label": "紀實自然光"}},
                    "round": {"audience_key": "warm_engaged", "recommended_slot": "explore"},
                },
                {
                    "fingerprint": {"look": {"key": "documentary", "label": "紀實自然光"}},
                    "round": {"audience_key": "warm_engaged", "recommended_slot": "explore"},
                },
            ],
            coordinates_json=None, llm_task_id=None,
        )
        # an old-shape row (no `round` key) never counts as a round
        workbench_repo.write_output(
            self.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief_id,
            part="image_prompt", generation_round=4,
            body_json={"fingerprint": {"look": {"key": "documentary"}}},
            coordinates_json=None, llm_task_id=None,
        )

        history = workbench_repo.look_history(
            self.conn, self.org_id, self.brand_id, "warm_engaged",
        )
        self.assertEqual(history, {
            "soft_lifestyle": {"adopted": 1, "offered": 2},
            "documentary": {"adopted": 0, "offered": 2},
        })

        other_audience = workbench_repo.look_history(
            self.conn, self.org_id, self.brand_id, "cold_unaware",
        )
        self.assertEqual(other_audience, {})

        round_history = workbench_repo.image_round_history(
            self.conn, self.org_id, self.brand_id,
        )
        self.assertEqual(round_history, {"rounds": 3, "explore_recommended": 2})

    def test_look_history_none_audience_matches_only_null_rows(self):
        brief_id = self._submit_set()
        self._write_round(
            brief_id, round_num=1, look="soft_lifestyle",
            audience_key=None, recommended_slot="exploit",
        )
        self._write_round(
            brief_id, round_num=2, look="soft_lifestyle",
            audience_key="warm_engaged", recommended_slot="exploit",
        )
        workbench_repo.write_output(
            self.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief_id,
            part="image_prompt", generation_round=3,
            body_json={"fingerprint": {}, "round": {"audience_key": None}},
            coordinates_json=None, llm_task_id=None,
        )

        history = workbench_repo.look_history(
            self.conn, self.org_id, self.brand_id, None,
        )
        self.assertEqual(history, {"soft_lifestyle": {"adopted": 0, "offered": 1}})
        self.assertNotIn(None, history)



if __name__ == "__main__":
    unittest.main()
