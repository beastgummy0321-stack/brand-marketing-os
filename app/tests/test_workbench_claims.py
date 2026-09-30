"""Regression for AUD-02: creative categories are not fulfilment evidence."""
from unittest.mock import patch

import pytest

import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.tests.test_workbench_pack_api import _WorkbenchPackApiTestBase
from app.workbench import claims, repository

ACTOR = "測試員"


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
         patch.object(claims.bi_repo, "offer_sources", return_value=[]), \
         patch.object(claims.bi_repo, "list_claims_for_brand", return_value=[
             {"id": "other", "product_id": "other", "claim_type": "approved", "claim_text": "試飲"},
             {"id": "bad", "product_id": None, "claim_type": "forbidden", "claim_text": "折扣"},
             {"id": "risk", "product_id": None, "claim_type": "high_risk",
              "claim_text": "專家背書"},
         ]):
        assert claims.sources(None, "brand", None) == []
        facts.assert_called_once_with(None, "brand", status="confirmed")


def test_confirmed_proof_fact_is_a_prompt_source_without_risk_word():
    with patch.object(claims.bi_repo, "list_brand_facts", return_value=[
        {"id": "proof", "fact_type": "proof", "value": "SGS 重金屬檢驗合格"},
        {"id": "plain", "fact_type": "product", "value": "每包 20 公克"},
    ]), patch.object(claims.bi_repo, "list_claims_for_brand", return_value=[]), \
         patch.object(claims.bi_repo, "offer_sources", return_value=[]):
        rows = claims.sources(None, "brand", None)
    ids = [r["id"] for r in claims.prompt_sources(rows)]
    assert ids == ["proof"]
    text = claims.policy(rows)
    assert "## 優惠、背書與已登記的證據來源" in text
    assert "- [proof] SGS 重金屬檢驗合格" in text


def test_proof_rows_come_first_and_cap_stays_20():
    risky = [{"id": f"r{i}", "text": "折扣", "proof": False} for i in range(25)]
    proof = [{"id": "p", "text": "SGS 重金屬檢驗合格", "proof": True}]
    got = claims.prompt_sources(risky + proof)
    assert len(got) == 20
    assert got[0]["id"] == "p"


# -- F42-I03: the copy guard accepts the words of an offer the brand really has ---------------

_SHIP = "三盒 NT$999 免運"


def _offer_brand(policies: list, price: float | None) -> tuple[str, str]:
    """A brand with `policies` (bi_repo.save_brand_policies) and one product priced `price` NT$."""
    brand_id = bi_repo.create_brand(web.conn, org_id=coredb.DEV_ORG_ID, name="測試品牌：優惠守門",
                                    client_name=None, actor=ACTOR)["id"]
    product_id = bi_repo.create_product(web.conn, brand_id, name="測試軟糖", actor=ACTOR)["id"]
    if price is not None:
        bi_repo.save_product_economics(web.conn, brand_id, product_id, actor=ACTOR,
                                       selling_price=price, currency="TWD", confirmed_by=ACTOR)
    if policies:
        bi_repo.save_brand_policies(web.conn, brand_id, policies, actor=ACTOR)
    web.conn.commit()
    return brand_id, product_id


def _guard(policies: list, price: float | None, copy) -> tuple[list[dict], list[str]]:
    brand_id, product_id = _offer_brand(policies, price)
    rows = claims.sources(web.conn, brand_id, product_id)
    return rows, claims.unsupported(copy, rows)


_SHIP_999 = [{"key": "ship_threshold", "params": {"threshold": 999}}]


def test_free_shipping_policy_covers_product_at_threshold():
    rows, missing = _guard(_SHIP_999, 999, {"headline": _SHIP})
    assert rows == [
        {"id": "offer:free_shipping", "text": "滿 NT$999 免運", "proof": False,
         "offer_key": "free_shipping"},
    ]
    assert missing == []


def test_free_shipping_policy_below_threshold_is_flagged():
    rows, missing = _guard(_SHIP_999, 998, {"headline": _SHIP})
    assert rows == []  # the policy reaches the copy only through offer_sources
    assert "滿 NT$999 免運" not in claims.policy(rows)
    assert missing == ["免運"]


def test_no_policy_flags_as_before():
    rows, missing = _guard([], 999, {"headline": _SHIP})
    assert rows == []
    assert missing == ["免運"]


def test_proof_words_keep_the_exact_sentence_rule_beside_an_offer():
    _, missing = _guard(_SHIP_999, 999, {"body": f"{_SHIP}，專家推薦"})
    assert missing == ["專家推薦"]


def test_first_order_discount_policy():
    first = [{"key": "first_order", "params": {"content": "首購 9 折"}}]
    for copy in ("首購 9 折", "首購9折，優惠只到結帳"):
        _, missing = _guard(first, 999, {"headline": copy})
        assert missing == [], copy
    # Without the policy the same words are flagged as today.
    assert _guard([], 999, {"headline": "首購9折"})[1] == ["9折"]


def test_available_family_does_not_cover_other_offer_families():
    rows = [{"id": "offer:free_shipping", "text": "滿 NT$999 免運", "proof": False,
             "offer_key": "free_shipping"}]
    assert claims.unsupported("免運又加贈試吃包，退款保證", rows) == ["加贈", "試吃", "退款保證"]
    assert claims.unsupported("免運優惠", rows) == []  # 優惠 counts when any offer is present
    assert claims.unsupported("優惠", []) == ["優惠"]


def test_offer_rows_are_prompt_sources_with_their_ids():
    rows, _ = _guard([{"key": "first_order", "params": {"content": "首購 9 折"}}], 999, "")
    text = claims.policy(rows)
    assert "- [offer:discount] 新會員首購禮：首購 9 折" in text
    assert text.count("新會員首購禮：首購 9 折") == 1  # only the offer row, not the policy fact


def test_cooling_off_exemption_is_not_a_copy_source():
    disclosure = "本店商品為易腐敗之食品，依法不適用七天猶豫期。"
    rows, _ = _guard([{"key": "cooling_off_exempt", "params": {"disclosure": disclosure}}],
                     999, "")
    assert rows == []


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


# -- F34-I02 (Contract S): 食安法 §28 wording reminder ------------------------------------------

_FOOD_TEXT = "十分鐘內治療你的午後疲勞，幫你減肥又提神，健康食品等級，早上吃還能改善便秘、降血糖。"


def test_statutory_hits_with_expected_tiers_for_food_tw():
    hits = claims.statutory({"body": _FOOD_TEXT}, "food_tw")
    tiers = {h["term"]: h["tier"] for h in hits}
    assert tiers["治療"] == "medical"
    assert tiers["減肥"] == "function"
    assert tiers["健康食品"] == "health_food"
    assert tiers["改善便秘"] == "medical"
    assert tiers["降血糖"] == "medical"
    assert all(h["basis"] for h in hits)


@pytest.mark.parametrize("text", ["幫助消化", "改善生活", "調整體質", "精神旺盛"])
def test_statutory_allowed_or_bare_phrases_do_not_hit(text):
    assert claims.statutory({"body": text}, "food_tw") == []


def test_statutory_is_empty_without_regime():
    assert claims.statutory({"body": _FOOD_TEXT}, None) == []
    assert claims.statutory_warning([]) is None


def test_statutory_warning_carries_terms_labels_and_closing_sentence():
    warning = claims.statutory_warning(claims.statutory({"body": _FOOD_TEXT}, "food_tw"))
    assert warning is not None
    assert {t["term"]: t["tier_label"] for t in warning["terms"]} == {
        "治療": "醫療效能", "減肥": "改變生理功能", "健康食品": "未取得許可不得使用",
        "改善便秘": "醫療效能", "降血糖": "醫療效能",
    }
    assert warning["sentence"] == "食品廣告通常不能這樣講（食安法第 28 條）。確認無誤仍可選定。"
    assert warning["href"] == "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0040140"
    ads = claims.statutory_warning(claims.statutory("治療", "food_tw"),
                                   closing="確認無誤仍可確認安排。")
    assert ads is not None
    assert ads["sentence"].endswith("確認無誤仍可確認安排。")
