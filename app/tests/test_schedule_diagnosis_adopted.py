"""app/tests/test_schedule_diagnosis_adopted.py — F31-I06 (Contract K).

Each suggestion in the brand diagnosis response carries `adopted: bool`, computed with the same
key `_run_diagnosis_adopt()` dedupes on (`rule_type` + `adopt_content`). Before this, "已採用"
lived only in frontend state, so a reload turned every adopted suggestion back into "採用".
"""

import unittest
from uuid import UUID, uuid4

import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.identity import ActorContext
from app.schedule import diagnosis
from app.schedule import routes as schedule_routes
from app.schedule import state as schedule_state


def _suggestion(headline: str) -> dict:
    return {
        "dimension": "audience", "coordinate_key": "cold_problem_aware",
        "coordinate_label": "陌生・知道問題", "direction": "scale_up",
        "impact_spend": 500.0, "headline": headline,
        "evidence": "這群人保守 ROAS 2.58x／樂觀 3.17x、覆蓋率 75%", "agreed_by": ["budget"],
    }


class DiagnosisAdoptedFlagTest(unittest.TestCase):
    def _new_brand(self) -> tuple[str, str]:
        org_id = f"org_diag_adopted_{uuid4().hex[:8]}"
        web.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (org_id, org_id),
        )
        web.conn.commit()
        brand_id = bi_repo.create_brand(
            web.conn, org_id=org_id, name=f"測試品牌{uuid4().hex[:6]}",
            client_name=None, actor="測試員",
        )["id"]
        return org_id, brand_id

    def _insert_round(self, org_id: str, brand_id: str, suggestions: list[dict]) -> None:
        # Same direct-SQL seeding as test_schedule_diagnosis.AdoptSuggestionTest: a succeeded
        # round of three lens rows, the budget row carrying the converged suggestions.
        started_at = coredb.now_utc()
        round_id = coredb.new_id("dgr")
        for lens in diagnosis.LENSES:
            web.conn.execute(
                "INSERT INTO llm_task (id, org_id, brand_id, task_type, context_scope_json,"
                " input_context_ids_json, input_context_hash, knowledge_item_ids_json,"
                " brand_version, prompt_template_id, prompt_template_version, provider, model,"
                " status, attempt_no, started_at, structured_output_json)"
                " VALUES (%s, %s, %s, %s, %s, '[]', '', '[]', 1, 'p', 'v1', 'seed', 'seed',"
                " 'succeeded', 1, %s, %s)",
                (coredb.new_id("llm"), org_id, brand_id, schedule_state.DIAGNOSIS_TASK_TYPE,
                 coredb.jsonb({"brand_id": brand_id, "round_id": round_id, "lens": lens}),
                 started_at,
                 coredb.jsonb(suggestions) if lens == "budget" else None),
            )
        web.conn.commit()

    def test_an_adopted_suggestion_reads_adopted_on_the_next_get(self):
        org_id, brand_id = self._new_brand()
        self._insert_round(org_id, brand_id, [_suggestion("加碼甲"), _suggestion("加碼乙")])

        before = diagnosis.brand_diagnosis_response(web.conn, org_id, brand_id)
        self.assertEqual([s["adopted"] for s in before["suggestions"]], [False, False])

        actor = ActorContext(
            user_id=UUID(int=0), org_id=org_id, role="owner", email="t@example.com",
        )
        schedule_routes._run_diagnosis_adopt(
            web.conn, brand_id, actor, schedule_routes.AdoptRequest(suggestion_index=1),
        )

        after = diagnosis.brand_diagnosis_response(web.conn, org_id, brand_id)
        self.assertEqual([s["adopted"] for s in after["suggestions"]], [False, True])

    def test_a_rule_for_a_single_product_does_not_mark_the_suggestion_adopted(self):
        # The adopt route only counts brand-wide rules (product_id IS NULL) as "already adopted";
        # the flag must use the same key, not a looser one.
        org_id, brand_id = self._new_brand()
        suggestion = _suggestion("加碼甲")
        self._insert_round(org_id, brand_id, [suggestion])
        round_date, _ = diagnosis.latest_round(web.conn, brand_id)
        rule_type, content = diagnosis.adopt_key(suggestion, round_date)
        product_id = bi_repo.create_product(web.conn, brand_id, name="商品甲", actor="測試員")["id"]
        bi_repo.create_rule(
            web.conn, brand_id, actor="測試員", rule_type=rule_type, content=content,
            severity="soft", source_reference_id=None, product_id=product_id,
        )

        response = diagnosis.brand_diagnosis_response(web.conn, org_id, brand_id)
        self.assertEqual([s["adopted"] for s in response["suggestions"]], [False])


if __name__ == "__main__":
    unittest.main()
