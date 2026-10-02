"""Regression for AUD-02: creative categories are not fulfilment evidence."""
from unittest.mock import patch

import pytest

import app.shared.web as web
import app.workbench as workbench_module
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


def _policy_id(brand_id: str, fact_key: str) -> str:
    return next(r["id"] for r in bi_repo.list_brand_facts(web.conn, brand_id, status="confirmed")
                if r["fact_type"] == "policy" and r["fact_key"] == fact_key)


def test_free_shipping_policy_covers_product_at_threshold():
    brand_id, product_id = _offer_brand(_SHIP_999, 999)
    rows = claims.sources(web.conn, brand_id, product_id)
    # F43 lead note: the id names its source (here the policy fact), not only the offer key.
    assert rows == [
        {"id": f"offer:free_shipping:{_policy_id(brand_id, 'ship_threshold')}",
         "text": "滿 NT$999 免運", "proof": False, "offer_key": "free_shipping"},
    ]
    assert claims.unsupported({"headline": _SHIP}, rows) == []


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
    for copy in ("首購 9 折", "首購9折，只到結帳"):
        _, missing = _guard(first, 999, {"headline": copy})
        assert missing == [], copy
    # F46 Contract O: 「優惠」 is backed only when the offer sentence itself says 優惠.
    assert _guard(first, 999, {"headline": "首購9折，優惠只到結帳"})[1] == ["優惠"]
    # Without the policy the same words are flagged as today.
    assert _guard([], 999, {"headline": "首購9折"})[1] == ["9折"]


def test_available_family_does_not_cover_other_offer_families():
    rows = [{"id": "offer:free_shipping", "text": "滿 NT$999 免運", "proof": False,
             "offer_key": "free_shipping"}]
    assert claims.unsupported("免運又加贈試吃包，退款保證", rows) == ["加贈", "試吃", "退款保證"]
    # F46 Contract O: 優惠 is backed only by an offer sentence that writes 優惠.
    assert claims.unsupported("免運優惠", rows) == ["優惠"]
    assert claims.unsupported("優惠", []) == ["優惠"]


def test_offer_rows_are_prompt_sources_with_their_ids():
    brand_id, product_id = _offer_brand(
        [{"key": "first_order", "params": {"content": "首購 9 折"}}], 999)
    text = claims.policy(claims.sources(web.conn, brand_id, product_id))
    policy_id = _policy_id(brand_id, "first_order")
    assert f"- [offer:discount:{policy_id}] 新會員首購禮：首購 9 折" in text
    assert text.count("新會員首購禮：首購 9 折") == 1  # only the offer row, not the policy fact


def test_cooling_off_exemption_is_not_a_copy_source():
    disclosure = "本店商品為易腐敗之食品，依法不適用七天猶豫期。"
    rows, _ = _guard([{"key": "cooling_off_exempt", "params": {"disclosure": disclosure}}],
                     999, "")
    assert rows == []


# -- F43-I03: a sell-way reads every knowledge product; its own price sentence is a source ------

_THREE_PACK = "三盒組優惠價 NT$999（原價 NT$1,197）"
# F45: the sell-way's own registered sentence carries no product name.
_OWN_PRICE = "優惠價 NT$999（原價 NT$1,197）"


def _knowledge_product(brand_id: str, name: str, fact: str, claim: str) -> str:
    product_id = bi_repo.create_product(web.conn, brand_id, name=name, actor=ACTOR)["id"]
    bi_repo.create_product_fact(web.conn, brand_id, product_id, actor=ACTOR, fact_type="ingredient",
                                label="成分", value=fact, status="confirmed", confirmed_by=ACTOR)
    bi_repo.create_claim(web.conn, brand_id, actor=ACTOR, claim_text=claim, claim_type="approved",
                         product_id=product_id)
    return product_id


def _sell_way(brand_id: str, name: str, components: list, price: float,
              list_price: float | None) -> str:
    """F45: one product × 1 -> a base sell-way of it; else a composed sell-way of each
    product's 單盒 base."""
    economics = {"selling_price": price, "list_price": list_price,
                 "unit_variable_cost": 300, "shipping_cost": 60}
    if len(components) == 1 and components[0][1] == 1:
        return bi_repo.save_sell_way(web.conn, brand_id, name=name, actor=ACTOR,
                                     product_id=components[0][0], economics=economics)["id"]
    bases = [bi_repo.save_sell_way(web.conn, brand_id, name="單盒", actor=ACTOR, product_id=p,
                                   economics={"selling_price": 399})["id"]
             for p, _qty in components]
    return bi_repo.save_sell_way(
        web.conn, brand_id, name=name, actor=ACTOR, economics=economics,
        components=[{"sell_way_id": b, "qty": q}
                    for b, (_p, q) in zip(bases, components, strict=True)],
    )["id"]


def _brand(policies: list | None = None) -> str:
    brand_id = bi_repo.create_brand(web.conn, org_id=coredb.DEV_ORG_ID, name="測試品牌：賣法來源",
                                    client_name=None, actor=ACTOR)["id"]
    if policies:
        bi_repo.save_brand_policies(web.conn, brand_id, policies, actor=ACTOR)
    return brand_id


def test_bundle_sources_read_every_knowledge_product():
    brand_id = _brand()
    gummy = _knowledge_product(brand_id, "晨光軟糖", "每顆含維生素C 60mg", "晨光軟糖一天兩顆")
    tea = _knowledge_product(brand_id, "午後花茶", "洛神花與玫瑰花瓣", "午後花茶冷泡也好喝")
    _knowledge_product(brand_id, "別的商品", "別的商品的成分", "別的商品的說法")
    brand_claim = bi_repo.create_claim(web.conn, brand_id, actor=ACTOR, claim_text="台灣製造",
                                       claim_type="approved")
    bundle = _sell_way(brand_id, "早午組合", [(gummy, 1), (tea, 1)], 999, 1300)
    rows = claims.sources(web.conn, brand_id, bundle)
    facts = {f["value"]: f["id"] for p in (gummy, tea)
             for f in bi_repo.list_product_facts(web.conn, brand_id, p)}
    product_claims = {c["claim_text"]: c["id"] for p in (gummy, tea)
                      for c in bi_repo.list_claims_for_product(web.conn, brand_id, p)}
    # The sources rows of a two-product bundle (evidence for the issue's Verify).
    assert rows == [
        {"id": facts["每顆含維生素C 60mg"], "text": "每顆含維生素C 60mg", "proof": False},
        {"id": facts["洛神花與玫瑰花瓣"], "text": "洛神花與玫瑰花瓣", "proof": False},
        {"id": product_claims["晨光軟糖一天兩顆"], "text": "晨光軟糖一天兩顆", "proof": False},
        {"id": brand_claim["id"], "text": "台灣製造", "proof": False},
        {"id": product_claims["午後花茶冷泡也好喝"], "text": "午後花茶冷泡也好喝", "proof": False},
        {"id": f"offer:bundle:{bundle}", "text": "優惠價 NT$999（原價 NT$1,300）",
         "proof": False, "offer_key": "bundle"},
    ]
    assert not [r for r in rows if "別的商品" in r["text"]]


def test_sell_way_price_sentence_backs_its_offer_words():
    brand_id = _brand()
    gummy = _knowledge_product(brand_id, "測試軟糖", "每包 20 公克", "測試軟糖好吃")
    three = _sell_way(brand_id, "三盒組", [(gummy, 3)], 999, 1197)
    rows = claims.sources(web.conn, brand_id, three)
    offers = [r for r in rows if r.get("offer_key")]
    assert offers == [{"id": f"offer:bundle:{three}", "text": _OWN_PRICE,
                       "proof": False, "offer_key": "bundle"}]
    assert claims.unsupported({"headline": _THREE_PACK}, rows) == []
    assert f"- [offer:bundle:{three}] {_OWN_PRICE}" in claims.policy(rows)
    # The family is the sell-way's (bundle), not every offer word.
    assert claims.unsupported({"headline": "三盒組免運"}, rows) == ["免運"]


def test_sell_way_without_a_lower_price_does_not_back_youhui():
    brand_id = _brand()
    gummy = _knowledge_product(brand_id, "測試軟糖", "每包 20 公克", "測試軟糖好吃")
    same = _sell_way(brand_id, "三盒組", [(gummy, 3)], 999, 999)
    rows = claims.sources(web.conn, brand_id, same)
    assert not [r for r in rows if r.get("offer_key")]
    # F46 Contract O widened RISK with 原價.
    assert claims.unsupported({"headline": _THREE_PACK}, rows) == ["優惠", "原價"]


def test_policy_and_sell_way_sharing_an_offer_key_get_their_own_rows():
    brand_id = _brand([{"key": "first_order", "params": {"content": "首購 9 折"}}])
    gummy = _knowledge_product(brand_id, "測試軟糖", "每包 20 公克", "測試軟糖好吃")
    single = _sell_way(brand_id, "單盒特價", [(gummy, 1)], 800, 1000)
    offers = [r for r in claims.sources(web.conn, brand_id, single) if r.get("offer_key")]
    assert offers == [
        {"id": f"offer:discount:{_policy_id(brand_id, 'first_order')}",
         "text": "新會員首購禮：首購 9 折", "proof": False, "offer_key": "discount"},
        {"id": f"offer:discount:{single}",
         "text": "優惠價 NT$800（原價 NT$1,000）",
         "proof": False, "offer_key": "discount"},
    ]


# -- F44-I01 (Contract B): the ad's offer coordinate narrows the offer rows ---------------------

_OFFER_NONE_LINE = "這則廣告的優惠座標是無優惠：不寫任何優惠、優惠價或原價（售價可以寫）。"
_OFFER_CARRY_LINE = "這則廣告要帶下面 [offer:…] 這個優惠：每一組文案都把它的原字句寫進標題或內文。"


def _three_pack_with_free_shipping(brand_id: str | None = None) -> tuple[str, str]:
    """A sell-way with its own list-price offer (`bundle`) under a 滿 NT$999 免運 store policy."""
    if brand_id is None:
        brand_id = _brand(_SHIP_999)
    else:
        bi_repo.save_brand_policies(web.conn, brand_id, _SHIP_999, actor=ACTOR)
    gummy = _knowledge_product(brand_id, "測試軟糖", "每包 20 公克", "測試軟糖好吃")
    return brand_id, _sell_way(brand_id, "三盒組", [(gummy, 3)], 999, 1197)


def test_offer_coordinate_narrows_only_the_offer_rows():
    brand_id, three = _three_pack_with_free_shipping()
    every = claims.sources(web.conn, brand_id, three)
    plain = [r for r in every if not r.get("offer_key")]
    ship = {"id": f"offer:free_shipping:{_policy_id(brand_id, 'ship_threshold')}",
            "text": "滿 NT$999 免運", "proof": False, "offer_key": "free_shipping"}
    bundle = {"id": f"offer:bundle:{three}", "text": _OWN_PRICE,
              "proof": False, "offer_key": "bundle"}
    assert [r["text"] for r in plain] == ["每包 20 公克", "測試軟糖好吃"]
    assert every == [*plain, ship, bundle]  # no offer_key = today's rows
    assert claims.sources(web.conn, brand_id, three, None) == every
    assert claims.sources(web.conn, brand_id, three, "none") == plain
    assert claims.sources(web.conn, brand_id, three, "bundle") == [*plain, bundle]
    assert claims.sources(web.conn, brand_id, three, "free_shipping") == [*plain, ship]


def test_policy_says_what_the_offer_coordinate_asks_for():
    brand_id, three = _three_pack_with_free_shipping()

    def block(offer_key):
        return claims.policy(claims.sources(web.conn, brand_id, three, offer_key), offer_key)

    unchanged = block(None)
    assert _OFFER_NONE_LINE not in unchanged and _OFFER_CARRY_LINE not in unchanged
    assert unchanged == claims.policy(claims.sources(web.conn, brand_id, three))

    none = block("none")
    assert _OFFER_NONE_LINE in none.split("\n")
    assert _OFFER_CARRY_LINE not in none
    assert "- [offer:" not in none
    assert "（沒有已確認的優惠或背書來源）" in none

    bundle = block("bundle")
    row = f"- [offer:bundle:{three}] {_OWN_PRICE}"
    assert _OFFER_CARRY_LINE in bundle.split("\n")
    assert _OFFER_NONE_LINE not in bundle
    assert bundle.index(_OFFER_CARRY_LINE) < bundle.index(row)  # 「下面」: the line sits above
    assert "滿 NT$999 免運" not in bundle

    # A key with no row left reads as no offer.
    gone = block("trial_sample")
    assert _OFFER_NONE_LINE in gone.split("\n")
    assert "- [offer:" not in gone


def test_validate_claims_judges_against_the_offer_coordinate():
    brand_id, three = _three_pack_with_free_shipping()

    def missing(**kwargs):
        return workbench_module.validate_claims(
            web.conn, coredb.DEV_ORG_ID, brand_id, three, {"headline": _THREE_PACK}, **kwargs,
        )["unsupported_promises"]

    assert missing() == []  # existing positional callers: every available offer backs it
    assert missing(offer_key="none") == ["優惠", "原價"]  # F46: 原價 is a RISK word
    assert missing(offer_key="bundle") == []


# -- F46-I02 (Contract O): 「帶了就要寫」 and narrower offer-word backing -------------------------

_BUNDLE_SENTENCE = "三盒組優惠價 NT$999（原價 NT$1,500）"
_BUNDLE_ROWS = [{"id": "offer:bundle:sw", "text": _BUNDLE_SENTENCE, "proof": False,
                 "offer_key": "bundle"}]
_SHIP_ROWS = [{"id": "offer:free_shipping:p", "text": "滿 NT$999 免運", "proof": False,
               "offer_key": "free_shipping"}]


def test_missing_offer_names_the_sentence_only_when_absent():
    present = {"headline": f"{_BUNDLE_SENTENCE}，一次帶走", "body": "每天兩顆"}
    assert claims.missing_offer(present, _BUNDLE_ROWS, "bundle") == []
    assert claims.missing_offer({"headline": "一次帶走三盒"}, _BUNDLE_ROWS, "bundle") == [
        _BUNDLE_SENTENCE]
    # Whitespace differs on either side and still matches.
    spaced = {"body": "三盒組 優惠價NT$999 （原價NT$1,500）"}
    assert claims.missing_offer(spaced, _BUNDLE_ROWS, "bundle") == []
    # Metadata never counts as copy.
    assert claims.missing_offer({"coordinates": {"offer": _BUNDLE_SENTENCE}},
                                _BUNDLE_ROWS, "bundle") == [_BUNDLE_SENTENCE]


@pytest.mark.parametrize("offer_key", [None, "none", "discount"])
def test_missing_offer_is_empty_without_an_offer_row(offer_key):
    assert claims.missing_offer({"headline": "一次帶走三盒"}, _BUNDLE_ROWS, offer_key) == []


def test_offer_word_backed_only_by_its_exact_term_in_an_offer_sentence():
    # 「買一送一」 on a bundle ad: the bundle's price sentence does not say it.
    assert claims.unsupported({"headline": "三盒組買一送一"}, _BUNDLE_ROWS) == ["買一送"]
    # The words the bundle sentence does write are backed.
    assert claims.unsupported({"headline": "優惠價 NT$999，原價 NT$1,500"}, _BUNDLE_ROWS) == []
    # 「免運」 with a policy sentence that writes 免運 is backed.
    assert claims.unsupported({"headline": "三盒免運"}, _SHIP_ROWS) == []
    # 「優惠」 with only a free-shipping sentence is not.
    assert claims.unsupported({"headline": "免運優惠"}, _SHIP_ROWS) == ["優惠"]
    # Proof words keep the exact-sentence rule even when an offer sentence writes them.
    rows = [{**_BUNDLE_ROWS[0], "text": "專家推薦三盒組優惠價 NT$999"}]
    assert claims.unsupported({"body": "專家推薦"}, rows) == ["專家推薦"]


@pytest.mark.parametrize(("text", "term"), [
    ("第二件半價", "第二件半價"), ("今天半價", "半價"), ("週末特價", "特價"), ("會員特惠", "特惠"),
    ("全面下殺", "下殺"), ("限時三天", "限時"), ("原價一千", "原價"), ("早鳥價開跑", "早鳥價"),
    ("加購價199", "加購價"), ("組合價更划算", "組合價"), ("結帳現折", "現折"),
    ("滿額再出發", "滿額"), ("滿千送百", "滿千送"), ("滿1000折100", "滿1000折"),
    ("再送一包", "再送"), ("加送一包", "加送"),
    ("送2包", "送2"), ("會員回饋", "回饋"), ("點數加倍", "點數"), ("留言抽獎", "抽獎"),
])
def test_widened_risk_words_are_detected_once(text, term):
    assert claims.unsupported({"body": text}, []) == [term]


@pytest.mark.parametrize("text", ["中秋送禮首選", "送貨到府", "贈送小卡", "優惠價"])
def test_bare_song_is_not_a_risk_word(text):
    found = claims.unsupported({"body": text}, [])
    assert found == (["優惠"] if text == "優惠價" else []), text


def test_validate_claims_reports_missing_offer():
    brand_id, three = _three_pack_with_free_shipping()
    copy = {"headline": "三盒一次帶走", "body": "每天兩顆，通勤也方便"}

    def check(**kwargs):
        return workbench_module.validate_claims(
            web.conn, coredb.DEV_ORG_ID, brand_id, three, copy, **kwargs)

    result = check(offer_key="bundle")
    assert result == {
        "unsupported_promises": [], "scope": "fulfilment_and_endorsement_families",
        "statutory_hits": [], "statutory_warning": None, "missing_offer": [_OWN_PRICE],
    }
    assert check(offer_key="none")["missing_offer"] == []
    assert check()["missing_offer"] == []
    with_sentence = {**copy, "headline": f"三盒一次帶走｜{_OWN_PRICE}"}
    assert workbench_module.validate_claims(
        web.conn, coredb.DEV_ORG_ID, brand_id, three, with_sentence, offer_key="bundle",
    )["missing_offer"] == []


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

    def test_offer_version_warns_on_a_no_offer_set_only(self):
        """F44-I01: the version reader narrows with the brief's own offer coordinate (key or
        label), so the sell-way's price sentence warns on an `offer=none` set and nowhere else."""
        _, three = _three_pack_with_free_shipping(self.brand_id)
        # Seed the brand's coordinate vocabulary so the label 「無優惠」 resolves to `none`.
        seeded = self.client.get(f"/api/schedule/brands/{self.brand_id}/coordinates")
        assert seeded.status_code == 200, seeded.text
        offers = {"key": "none", "label": "無優惠", "bundle": "bundle", "unset": None}
        pack = self._submit_pack([
            self._one_set(name, {"copy": 1}, product_id=three,
                          coordinates={"offer": offer} if offer else {})
            for name, offer in offers.items()
        ])
        warnings = {}
        for brief in self._briefs(pack):
            repository.write_output(
                web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief["id"],
                part="copy", generation_round=1,
                body_json=[{"sets": [{"headline": _THREE_PACK, "body": "三盒一次帶走"}]}],
                coordinates_json=None, llm_task_id=None,
            )
            detail = self.client.get(
                f"/api/workbench/brands/{self.brand_id}/sets/{brief['id']}"
            ).json()["set"]
            warnings[brief["name"]] = detail["products"]["copy"]["versions"][0]["claim_warning"]
        assert set(warnings) == {f"單元 {name}" for name in offers}
        for name in ("key", "label"):
            assert "優惠" in warnings[f"單元 {name}"]["message"], name
        assert warnings["單元 bundle"] is None
        assert warnings["單元 unset"] is None

    def test_offer_set_copy_without_its_sentence_warns(self):
        """F46-I02: a copy version on an offer set that writes none of the offer's registered
        sentences warns; with another unsupported word both land in one message."""
        _, three = _three_pack_with_free_shipping(self.brand_id)
        pack = self._submit_pack([self._one_set("1", {"copy": 1}, product_id=three,
                                                coordinates={"offer": "bundle"})])
        brief = self._briefs(pack)[0]
        missing_line = f"這組文案沒有寫這則廣告要帶的優惠：「{_OWN_PRICE}」。"

        def warning_for(round_no, sets):
            repository.write_output(
                web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief["id"],
                part="copy", generation_round=round_no, body_json=[{"sets": sets}],
                coordinates_json=None, llm_task_id=None,
            )
            detail = self.client.get(
                f"/api/workbench/brands/{self.brand_id}/sets/{brief['id']}"
            ).json()["set"]
            return detail["products"]["copy"]["versions"][0]["claim_warning"]

        alone = warning_for(1, [{"headline": "三盒一次帶走", "body": "通勤補給"}])
        assert alone == {"message": missing_line,
                         "href": f"/brands/{self.brand_id}/library?tab=claims"}
        merged = warning_for(2, [{"headline": "三盒買一送一", "body": "通勤補給"}])
        assert merged is not None
        assert merged["message"].startswith("「買一送」可能包含未確認的優惠")
        assert merged["message"].endswith(missing_line)
        assert merged["href"] == f"/brands/{self.brand_id}/library?tab=claims"


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
