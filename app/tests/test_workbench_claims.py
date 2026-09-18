"""Regression for AUD-02: creative categories are not fulfilment evidence."""
from unittest.mock import patch

import pytest

import app.shared.web as web
from app.tests.test_workbench_pack_api import _WorkbenchPackApiTestBase
from app.workbench import claims, repository


@pytest.mark.parametrize("value", [
    {"body": "想先確認口味，可先試喝一包，再決定20入單盒。"},
    {"scenes": [{"voiceover": "先申請試飲，再決定", "overlay": "【模擬測試】先申請試飲"}]},
    {"cards": [{"headline": ["秋季優惠"], "prompt": "先看20入單盒的折扣資訊"}]},
    {"body": "專家背書、顧客好評"},
])
def test_unsupported_promises_in_all_formats(value):
    assert claims.unsupported(value, [])


def test_exact_confirmed_terms_and_fulfilment_only():
    statement = "試飲每人限一包，請至 https://example.test/trial 申請"
    rows = [{"id": "fact", "text": statement}]
    assert claims.unsupported({"headline": statement}, rows) == []
    assert claims.unsupported({"headline": statement.replace("一包", "十包")}, rows)
    assert claims.unsupported("申請試飲", [{"id": "fact", "text": "試飲"}])
    assert claims.unsupported("尚未確認優惠", [{"id": "fact", "text": "尚未確認優惠"}])
    assert claims.unsupported("試飲每人限一包", [{"id": "fact", "text": "試飲每人限一包"}])


def test_metadata_is_not_a_consumer_promise():
    assert claims.unsupported({"body": "看看20入單盒的商品資訊", "coordinates": {"offer": "試飲"},
                               "warnings": ["不可虛構優惠"]}, []) == []


def test_pending_forbidden_other_product_never_support():
    with patch.object(claims.bi_repo, "list_brand_facts", return_value=[]) as facts, \
         patch.object(claims.bi_repo, "list_claims_for_brand", return_value=[
             {"id": "other", "product_id": "other", "claim_type": "approved", "claim_text": "試飲"},
             {"id": "bad", "product_id": None, "claim_type": "forbidden", "claim_text": "折扣"},
             {"id": "risk", "product_id": None, "claim_type": "high_risk",
              "claim_text": "專家背書"},
         ]):
        assert claims.sources(None, "brand", None) == []
        facts.assert_called_once_with(None, "brand", status="confirmed")


class TestAdoptionWarning(_WorkbenchPackApiTestBase):
    def test_legacy_output_warns_but_selection_and_pack_approval_continue(self):
        pack = self._submit_pack([self._one_set("1", {"copy": 1})])
        brief = self._briefs(pack)[0]
        out = repository.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief["id"],
            part="copy", generation_round=1,
            body_json=[{"sets": [{"body": "可先試喝一包，再決定20入單盒"}]}],
            coordinates_json=None, llm_task_id=None,
        )[0]
        detail = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/sets/{brief['id']}"
        ).json()["set"]
        warning = detail["products"]["copy"]["versions"][0]["claim_warning"]
        assert "試喝" in warning["message"]
        assert "可能包含" in warning["message"]
        assert warning["href"] == f"/brands/{self.brand_id}/library?tab=claims"
        response = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/sets/{brief['id']}/versions/{out['id']}/select"
        )
        assert response.status_code == 200
        saved = web.conn.execute(
            "SELECT adopted_at FROM workbench_output WHERE id = %s", (out["id"],),
        ).fetchone()
        assert saved is not None
        assert saved["adopted_at"] is not None
        # Reload preserves the selection; pack approval never re-blocks this warning.
        detail = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/sets/{brief['id']}"
        ).json()["set"]
        assert detail["products"]["copy"]["versions"][0]["selected_at"] is not None
        for key in repository._COMPLETION_KEYS:
            response = self.client.post(
                f"/api/workbench/brands/{self.brand_id}/packs/{pack}/completion",
                json={"key": key, "checked": True},
            )
            assert response.status_code == 200
        response = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/packs/{pack}/approve"
        )
        assert response.status_code == 200
        assert response.json()["pack"]["status"] == "done"
