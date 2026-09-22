"""app/tests/test_ads_result_kinds.py — F19-I06 falsifiers: `app/ads/result_kinds.py` is the one
Chinese vocabulary for a campaign's own "result" kind. Every kind an adapter can actually produce
must have a label here (enumerated straight from the adapter's own tables, never a copy-pasted
list that could silently drift); an unknown or missing kind always falls back to the generic
「成果」, never a raw code; `PUT .../target` rejects a `result_kind` outside the vocabulary and
stores nothing.
"""

import unittest

import app.shared.web as web
from app.ads import external_repository as external
from app.ads import repository, result_kinds
from app.ads.adapters import meta_read
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb


def _meta_adapter_kinds() -> set[str]:
    """Every result kind the Meta adapter's own tables can produce (`app/ads/adapters/
    meta_read.py`) -- read-only, re-derived straight from those tables so this test fails the
    moment a new kind is added there without a label, instead of trusting a second, divergent
    list."""
    kinds = {"purchase"} if meta_read._SALES_OBJECTIVES else set()
    kinds |= {result_label for result_label, _ in meta_read._OBJECTIVE_RESULT_ACTIONS.values()}
    return kinds


class ResultKindsVocabularyTest(unittest.TestCase):
    def test_every_adapter_kind_has_a_label(self):
        for kind in _meta_adapter_kinds():
            self.assertIn(kind, result_kinds.LABELS, f"{kind!r} has no Chinese label")

    def test_label_none_and_unknown_kind_fall_back_to_generic(self):
        self.assertEqual(result_kinds.label(None), "成果")
        self.assertEqual(result_kinds.label("not_a_real_kind"), "成果")

    def test_label_known_kind(self):
        self.assertEqual(result_kinds.label("purchase"), "購買")

    def test_options_cover_every_labelled_kind_in_stable_order(self):
        opts = result_kinds.options()
        self.assertEqual([o["kind"] for o in opts], list(result_kinds.LABELS.keys()))
        for option in opts:
            self.assertEqual(option["label"], result_kinds.LABELS[option["kind"]])
            self.assertEqual(set(option), {"kind", "label"})


class PutTargetResultKindTest(unittest.TestCase):
    def setUp(self):
        self.org_id = coredb.DEV_ORG_ID
        self.brand_id = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：成果詞彙", client_name=None,
            actor="測試員",
        )["id"]
        web.conn.commit()
        self.campaign_id = external.create_imported_campaign(
            web.conn, self.org_id, self.brand_id, name="既有活動",
        )["id"]
        web.conn.commit()

    def test_unknown_result_kind_is_rejected_and_nothing_stored(self):
        with self.assertRaises(ValueError) as ctx:
            repository.save_campaign_target(
                web.conn, self.org_id, self.brand_id, self.campaign_id,
                result_kind="not_a_real_kind", expected_revision=0, actor="測試員",
            )
        self.assertEqual(str(ctx.exception), "result_kind_unknown")
        campaign = repository.get_campaign(web.conn, self.org_id, self.brand_id, self.campaign_id)
        self.assertIsNone(campaign["result_kind"])
        self.assertEqual(campaign.get("target_revision") or 0, 0)

    def test_known_result_kind_is_stored(self):
        repository.save_campaign_target(
            web.conn, self.org_id, self.brand_id, self.campaign_id,
            result_kind="lead", expected_revision=0, actor="測試員",
        )
        campaign = repository.get_campaign(web.conn, self.org_id, self.brand_id, self.campaign_id)
        self.assertEqual(campaign["result_kind"], "lead")

    def test_get_target_response_carries_label_and_options(self):
        target = repository.get_campaign_target(
            web.conn, self.org_id, self.brand_id, self.campaign_id,
        )
        self.assertEqual(target["result_label"], "成果")  # 還沒有 result_kind
        self.assertEqual(target["result_kinds"], result_kinds.options())

        repository.save_campaign_target(
            web.conn, self.org_id, self.brand_id, self.campaign_id,
            result_kind="purchase", expected_revision=0, actor="測試員",
        )
        target = repository.get_campaign_target(
            web.conn, self.org_id, self.brand_id, self.campaign_id,
        )
        self.assertEqual(target["result_label"], "購買")


if __name__ == "__main__":
    unittest.main()
