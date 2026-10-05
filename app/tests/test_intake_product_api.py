"""app/tests/test_intake_product_api.py — product onboarding HTTP contract (F43-I05).

`/api/intake/brands/{b}/products*` and `/bundles*` (app/intake/routes_product_api.py): the
products page (a draft, a ready product, a bundle, a brand-scan suggestion); each step's GET with
nothing (`source="none"`), with a stored product prefill (`source="ai"` + note) and after its PUT
(`source="saved"`); PUT validation (400 + a Chinese message); sell-way numbers computed by the
program (break-even, derived list price / cost, offer labels with an F42 滿額免運 policy); 完成
refused without a sell-way; cross-org / cross-brand refusal. No LLM call anywhere. Brand and
product names are fictional.
"""

import os
import unittest
from uuid import uuid4

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-fake-intake-product-test")

from fastapi.testclient import TestClient  # noqa: E402

import app.intake as intake_module  # noqa: E402
import app.main as main  # noqa: E402
import app.shared.web as web  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.identity import repository as identity_repo  # noqa: E402
from app.intake import repository as ir  # noqa: E402

from .identity_test_helpers import mint_hs256  # noqa: E402

_SEQ = [0]
ACTOR = "商品建檔測試員"

_PRODUCT_PREFILL = {
    "intro": {"value": "一天一顆，12 種維生素與礦物質", "note": "商品頁"},
    "mechanism": {"value": "每顆含維生素 C 150 mg、B 群、D3、鋅", "note": "商品頁"},
    "difference": {"value": "", "note": ""},
    "groups": [
        {
            "who": "常加班的上班族",
            "pain_keys": ["effort"],
            "quote": "「每天吞藥丸好麻煩」",
            "when_used": "早上出門前",
            "note": "評論",
        },
        {"who": "不存在的煩惱", "pain_keys": ["made_up"], "quote": "", "when_used": "", "note": ""},
    ],
    "proof": [
        {"fact_key": "lab_report", "text": "SGS 重金屬檢驗合格（2026/06）", "note": "商品頁"}
    ],
    "claims": [
        {"text": "每顆含維生素 C 150 mg", "note": "商品頁"},
        {"text": "增強免疫力、預防感冒", "note": "商品頁"},
    ],
    "sell_ways": [{"name": "單盒", "qty": 1, "price": 399, "list_price": None, "note": "商品頁"}],
}


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        intake_module.register(main.app)

    # -- helpers ------------------------------------------------------------

    def _brand(self, prefill: dict | None = None) -> str:
        _SEQ[0] += 1
        resp = self.client.post(
            "/api/intake/brands", data={"brand_name": f"虛構商品建檔品牌{_SEQ[0]}"}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        bid = resp.json()["brand_id"]
        if prefill is not None:
            draft = ir.get_active_draft(web.conn, bid)
            assert draft is not None
            ir.update_draft(web.conn, bid, draft["id"], prefill_json=prefill)
        return bid

    def _url(self, bid: str, path: str) -> str:
        return f"/api/intake/brands/{bid}{path}"

    def _get(self, bid: str, path: str) -> dict:
        resp = self.client.get(self._url(bid, path))
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()["data"]

    def _put(self, bid: str, path: str, body: dict):
        return self.client.put(self._url(bid, path), json=body)

    def _ok_put(self, bid: str, path: str, body: dict) -> dict:
        resp = self._put(bid, path, body)
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()["data"]

    def _new_product(self, bid: str, name: str = "綜合維他命軟糖", **more) -> str:
        resp = self.client.post(self._url(bid, "/products"), json={"name": name, **more})
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()["data"]["product_id"]

    def _step(self, pid: str, path: str = "") -> str:
        return f"/products/{pid}/onboarding{path}"

    def _sell_ways(self, bid: str, pid: str, rows: list) -> dict:
        return self._ok_put(bid, self._step(pid, "/sell-ways"), {"sell_ways": rows})

    def _group(self, bid: str, pid: str, who: str = "上班族") -> dict:
        return self._ok_put(bid, self._step(pid, "/who"),
                            {"groups": [{"who": who, "pain_keys": ["effort"]}]})

    def _finished(self, bid: str, name: str, *, price=399, cost=90, shipping=60) -> str:
        pid = self._new_product(bid, name)
        self._sell_ways(
            bid,
            pid,
            [{"name": "單盒", "price": price, "cost": cost, "shipping": shipping}],
        )
        self._group(bid, pid)  # F50 Contract R: zero customer groups is not ready
        resp = self.client.post(self._url(bid, self._step(pid, "/complete")))
        self.assertEqual(resp.status_code, 200, resp.text)
        return pid

    def _base(self, bid: str, pid: str, name: str = "單盒") -> str:
        """The id of the product's base sell-way `name` (F45: a bundle lists base sell-ways)."""
        rows = self._get(bid, self._step(pid, "/sell-ways"))["sell_ways"]
        return next(r["id"] for r in rows if r["name"] == name and r["shape"] == "base")

    def _other_org_headers(self) -> dict:
        org_id = "org_intake_product_test_b"
        web.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (org_id, org_id),
        )
        user_id = uuid4()
        email = f"intake-product-{user_id.hex[:8]}@example.com"
        identity_repo.create_user(web.conn, user_id, email)
        identity_repo.create_membership(web.conn, org_id, user_id, "owner")
        web.conn.commit()
        return {
            "Authorization": f"Bearer {mint_hs256(sub=str(user_id), email=email)}",
            "X-Org-Id": org_id,
        }


# ---------------------------------------------------------------------------
# Products page
# ---------------------------------------------------------------------------


class ProductsPageTest(_Base):
    def test_list_shape_with_draft_ready_bundle_and_suggestion(self):
        bid = self._brand(
            {
                "products": [
                    {"name": "綜合維他命軟糖", "url": None},
                    {"name": "膠原蛋白飲", "url": "https://shop.example/c"},
                ]
            }
        )
        ready = self._finished(bid, "綜合維他命軟糖")
        probiotic = self._finished(bid, "益生菌軟糖", price=459, cost=110)
        self._ok_put(
            bid,
            self._step(ready, "/who"),
            {
                "groups": [
                    {"who": "上班族", "pain_keys": ["effort"]},
                    {"who": "運動族", "pain_keys": ["uncertainty"]},
                ]
            },
        )
        draft = self._new_product(bid, "魚油膠囊")
        resp = self.client.post(
            self._url(bid, "/bundles"),
            json={
                "name": "雙效組",
                "components": [
                    {"sell_way_id": self._base(bid, ready), "qty": 1},
                    {"sell_way_id": self._base(bid, probiotic), "qty": 1},
                ],
                "price": 799,
                "shipping": 60,
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)

        data = self._get(bid, "/products")
        by_name = {p["name"]: p for p in data["products"]}
        self.assertEqual(list(by_name), ["綜合維他命軟糖", "益生菌軟糖", "魚油膠囊"])
        vit = by_name["綜合維他命軟糖"]
        self.assertEqual((vit["state"], vit["step"]), ("ready", None))
        self.assertEqual(vit["summary"], "2 群顧客・證據 0・說法 0")
        self.assertIsNone(vit["thumbnail_url"])
        self.assertEqual(
            vit["sell_ways"],
            [
                {
                    "id": vit["sell_ways"][0]["id"],
                    "name": "單盒",
                    "shape": "base",
                    "price": 399.0,
                    "break_even": 249.0,
                    "offer_labels": [],
                }
            ],
        )
        fish = by_name["魚油膠囊"]
        self.assertEqual((fish["id"], fish["state"], fish["step"]), (draft, "draft", 1))
        self.assertEqual(fish["summary"], "建到一半：還沒確認商品資料")
        self.assertEqual(fish["sell_ways"], [])
        [bundle] = data["bundles"]
        self.assertEqual(
            (bundle["name"], bundle["price"], bundle["state"]), ("雙效組", 799.0, "ready")
        )
        self.assertEqual(bundle["break_even"], 799 - 200 - 60)
        self.assertEqual(bundle["offer_labels"], ["組合價 省 59"])
        self.assertEqual(bundle["thumbnails"], [])
        self.assertEqual(
            [(c["product_id"], c["product_name"], c["name"], c["qty"])
             for c in bundle["components"]],
            [(ready, "綜合維他命軟糖", "單盒", 1), (probiotic, "益生菌軟糖", "單盒", 1)],
        )
        self.assertEqual(bundle["components"][0]["sell_way_id"], self._base(bid, ready))
        self.assertEqual(
            data["suggestions"], [{"name": "膠原蛋白飲", "url": "https://shop.example/c"}]
        )

    def test_suggestion_hidden_by_a_product_with_its_page_url(self):
        bid = self._brand({"products": [
            {"name": "聯名 T-shirt Beast Prime", "url": "https://shop.example/tee"},
            {"name": "膠原蛋白飲", "url": "https://shop.example/c"},
        ]})
        self._new_product(bid, "聯名 T-shirt", page_url="https://shop.example/tee/")
        self.assertEqual(self._get(bid, "/products")["suggestions"],
                         [{"name": "膠原蛋白飲", "url": "https://shop.example/c"}])

    def test_dismissed_suggestion_never_comes_back(self):
        bid = self._brand({"products": [
            {"name": "膠原蛋白飲", "url": None}, {"name": "魚油膠囊", "url": None}]})
        resp = self.client.post(self._url(bid, "/products/suggestions/dismiss"),
                                json={"name": "膠原蛋白飲"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["data"]["suggestions"], [{"name": "魚油膠囊", "url": None}])
        draft = ir.get_active_draft(web.conn, bid)
        assert draft is not None
        self.assertEqual(draft["prefill_json"]["dismissed"], ["膠原蛋白飲"])
        self.assertEqual(self._get(bid, "/products")["suggestions"],
                         [{"name": "魚油膠囊", "url": None}])
        resp = self.client.post(self._url(bid, "/products/suggestions/dismiss"), json={})
        self.assertEqual(resp.status_code, 400)

    def test_create_sets_step_one_and_page_url_and_is_get_or_create(self):
        bid = self._brand()
        pid = self._new_product(bid, "綜合維他命軟糖", page_url="https://shop.example/vit")
        product = bi_repo.get_product(web.conn, bid, pid)
        assert product is not None
        self.assertEqual(
            (product["onboarding_step"], product["page_url"]), (1, "https://shop.example/vit")
        )
        again = self.client.post(self._url(bid, "/products"), json={"name": " 綜合維他命軟糖 "})
        self.assertEqual(again.json()["data"], {"product_id": pid, "created": False})
        for body in ({"name": ""}, {"name": "x", "page_url": "shop.example"},
                     {"name": "x", "page_url": "https://"}):
            resp = self.client.post(self._url(bid, "/products"), json=body)
            self.assertEqual(resp.status_code, 400, body)
        # F50 Contract I: a scheme alone is not a URL (`input_rules.url`, one sentence).
        self.assertEqual(
            resp.json()["error"],
            "商品頁網址「https://」不是完整的網址，請從 https:// 開始，例如 https://example.com。",
        )

    def test_sell_way_and_bundle_ids_are_not_products(self):
        bid = self._brand()
        pid = self._finished(bid, "綜合維他命軟糖")
        way_id = self._get(bid, self._step(pid, "/sell-ways"))["sell_ways"][0]["id"]
        self.assertEqual(
            self.client.get(self._url(bid, self._step(way_id, "/what"))).status_code, 404
        )
        self.assertEqual(self.client.get(self._url(bid, f"/bundles/{way_id}")).status_code, 404)


# ---------------------------------------------------------------------------
# Status and the four steps
# ---------------------------------------------------------------------------


class StepsTest(_Base):
    def setUp(self):
        super().setUp()
        self.bid = self._brand()
        self.pid = self._new_product(
            self.bid, "綜合維他命軟糖", page_url="https://shop.example/vit"
        )

    def _prefill(self, prefill: dict = _PRODUCT_PREFILL, status: str = "done") -> None:
        ir.save_product_prefill(web.conn, self.bid, self.pid, status=status, prefill_json=prefill)

    def test_status_running_then_prefill_then_failed(self):
        # F43-I06: a create with a page URL queues the product-page read
        data = self._get(self.bid, self._step(self.pid))
        self.assertEqual(
            {k: data[k] for k in ("step", "completed", "ready", "prefill_status", "prefill_error")},
            {"step": 1, "completed": False, "ready": False, "prefill_status": "running",
             "prefill_error": None},
        )
        self._prefill()
        self.assertEqual(self._get(self.bid, self._step(self.pid))["prefill_status"], "done")
        self._prefill({}, status="failed")
        data = self._get(self.bid, self._step(self.pid))
        self.assertEqual(data["prefill_status"], "failed")
        self.assertTrue(data["prefill_error"])

    def test_what_none_ai_saved_and_advance(self):
        what = self._get(self.bid, self._step(self.pid, "/what"))
        self.assertEqual(
            (what["name"], what["page_url"], what["photos"]),
            ("綜合維他命軟糖", "https://shop.example/vit", []),
        )
        self.assertEqual(what["intro"], {"value": "", "source": "none", "note": ""})
        self._prefill()
        what = self._get(self.bid, self._step(self.pid, "/what"))
        self.assertEqual(
            what["intro"],
            {"value": "一天一顆，12 種維生素與礦物質", "source": "ai", "note": "商品頁"},
        )
        self.assertEqual(what["difference"]["source"], "none")
        saved = self._ok_put(
            self.bid,
            self._step(self.pid, "/what"),
            {
                "name": "綜合維他命軟糖 Plus",
                "page_url": "https://shop.example/vit2",
                "intro": "一天一顆",
                "mechanism": "",
                "difference": "不用配水",
            },
        )
        self.assertEqual(saved["intro"], {"value": "一天一顆", "source": "saved", "note": ""})
        self.assertEqual(saved["mechanism"]["source"], "none")  # step saved: the AI is gone
        self.assertEqual(
            (saved["name"], saved["page_url"]), ("綜合維他命軟糖 Plus", "https://shop.example/vit2")
        )
        self.assertEqual(self._get(self.bid, self._step(self.pid))["step"], 2)
        resp = self._put(self.bid, self._step(self.pid, "/what"), {"name": "", "intro": "x"})
        self.assertEqual(resp.status_code, 400)

    def test_who_none_ai_saved_and_validation(self):
        who = self._get(self.bid, self._step(self.pid, "/who"))
        self.assertEqual(who["groups"], [])
        self.assertEqual(
            [p["key"] for p in who["pain_options"]],
            ["cost", "effort", "uncertainty", "availability", "experience", "identity"],
        )
        self._prefill()
        [group] = self._get(self.bid, self._step(self.pid, "/who"))["groups"]  # bad pain dropped
        self.assertEqual(
            (group["id"], group["who"], group["pain_keys"], group["source"], group["note"]),
            (None, "常加班的上班族", ["effort"], "ai", "評論"),
        )
        bad = [
            (
                {"groups": [{"who": f"第{i}群", "pain_keys": ["cost"]} for i in range(4)]},
                "最多 3 群",
            ),
            (
                {"groups": [{"who": "a", "pain_keys": ["cost", "effort", "identity"]}]},
                "最多挑 2 個",
            ),
            ({"groups": [{"who": "a", "pain_keys": ["made_up"]}]}, "不在六種煩惱裡"),
            ({"groups": [{"who": "", "pain_keys": ["cost"]}]}, "還沒寫是誰"),
            ({"groups": [{"who": "a", "pain_keys": []}]}, "1～2 個"),
        ]
        for body, message in bad:
            resp = self._put(self.bid, self._step(self.pid, "/who"), body)
            self.assertEqual(resp.status_code, 400, body)
            self.assertIn(message, resp.json()["error"])
        saved = self._ok_put(
            self.bid,
            self._step(self.pid, "/who"),
            {
                "groups": [
                    {**group, "source": "ai"},
                    {
                        "who": "運動族",
                        "pain_keys": ["uncertainty", "cost"],
                        "quote": "",
                        "when_used": "練完之後",
                    },
                ]
            },
        )
        self.assertEqual(
            [(g["who"], g["source"]) for g in saved["groups"]],
            [("常加班的上班族", "saved"), ("運動族", "saved")],
        )
        stored = bi_repo.list_customer_groups(web.conn, self.bid, self.pid)
        self.assertEqual([g["source"] for g in stored], ["ai", "user"])

    def test_evidence_none_ai_saved_statutory_and_unset(self):
        bi_repo.set_regulatory_regime(web.conn, self.bid, "food_tw", actor=ACTOR)
        empty = self._get(self.bid, self._step(self.pid, "/evidence"))
        self.assertEqual((empty["proof"], empty["claims"]), ([], []))
        self._prefill()
        data = self._get(self.bid, self._step(self.pid, "/evidence"))
        self.assertEqual(
            [(p["fact_key"], p["source"]) for p in data["proof"]], [("lab_report", "ai")]
        )
        plain, law = data["claims"]
        self.assertEqual(
            (plain["verdict"], plain["statutory"], plain["from_note"]), (None, None, "商品頁")
        )
        # F48 decision 13: a 食安法 hit is a reminder on the row, never a pre-set 不能講.
        self.assertIsNone(law["verdict"])
        self.assertTrue(law["statutory"]["term"])
        self.assertIn(law["statutory"]["term"], law["statutory"]["sentence"])

        resp = self._put(
            self.bid,
            self._step(self.pid, "/evidence"),
            {
                "proof": [],
                "claims": [
                    {"text": plain["text"], "verdict": None},
                    {"text": law["text"], "verdict": None},
                ],
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("還有 2 句沒選", resp.json()["error"])

        saved = self._ok_put(
            self.bid,
            self._step(self.pid, "/evidence"),
            {
                "proof": [
                    {"fact_key": "lab_report", "text": "SGS 重金屬檢驗合格（2026/06）"},
                    {"fact_key": "expert_endorsement", "text": ""},
                ],
                "claims": [
                    {"text": plain["text"], "verdict": "ok"},
                    {"text": law["text"], "verdict": "ok"},
                ],
            },
        )  # F48 decision 13: 「可以講」 survives the statutory hit
        self.assertEqual(
            [(p["fact_key"], p["source"]) for p in saved["proof"]], [("lab_report", "saved")]
        )
        self.assertEqual(
            [(c["verdict"], c["source"]) for c in saved["claims"]],
            [("ok", "saved"), ("ok", "saved")],
        )
        # The reminder still rides on the saved row.
        self.assertEqual(saved["claims"][1]["statutory"], law["statutory"])
        types = {
            c["claim_text"]: c["claim_type"]
            for c in bi_repo.list_claims_for_product(web.conn, self.bid, self.pid)
        }
        self.assertEqual(types, {plain["text"]: "approved", law["text"]: "approved"})
        resp = self._put(
            self.bid,
            self._step(self.pid, "/evidence"),
            {"proof": [{"fact_key": "made_up", "text": "x"}], "claims": []},
        )
        self.assertEqual(resp.status_code, 400)

    def test_sell_ways_none_ai_saved_and_validation(self):
        self.assertEqual(self._get(self.bid, self._step(self.pid, "/sell-ways"))["sell_ways"], [])
        self._prefill()
        data = self._get(self.bid, self._step(self.pid, "/sell-ways"))
        [ai] = data["sell_ways"]
        self.assertEqual(
            (ai["id"], ai["name"], ai["price"], ai["source"], ai["break_even"]),
            (None, "單盒", 399.0, "ai", None),
        )
        self.assertFalse(data["show_close_rate"])
        self.assertIn("gross_margin", data["assumptions"])
        self.assertNotIn("close_rate", data["assumptions"])
        for rows, message in (
            ([], "至少要有一種賣法"),
            ([{"name": "單盒", "price": -1}], "「單盒」的售價要大於 0。"),
            ([{"name": "單盒", "price": 0}], "「單盒」的售價要大於 0。"),
            ([{"name": "單盒"}], "「單盒」的售價請填數字。"),  # a base needs its price
            # F50 Contract I: one rule per field on every path (the store refuses the same).
            ([{"name": "單盒", "price": 399, "cap_per_sale": 0}], "「單盒」的每筆上限要大於 0。"),
            ([{"name": "單盒", "price": 1280, "list_price": 999}],
             "售價（1280）不能大於原價（999）。"),
            ([{"name": "單盒", "price": 399, "cost": -5}], "不能是負數"),
            ([{"name": "單盒", "qty": 1, "price": 399}], "不用填數量"),  # F45: no qty key
            ([{"name": "單盒", "price": 399}, {"name": "單盒", "price": 1}], "重複"),
            (
                [{"name": "單盒", "price": 399},
                 {"name": "一盒", "components": [{"base": "單盒", "qty": 1}]}],
                "數量至少 2",
            ),
            (
                [{"name": "單盒", "price": 399},
                 {"name": "三盒", "components": [{"base": "體驗包", "qty": 3}]}],
                "不是這裡的基本賣法",
            ),
            (
                [{"name": "單盒", "price": 399},
                 {"name": "三盒", "components": [{"base": "單盒", "qty": 0}]}],
                "「三盒」裡「單盒」的數量要是 1 以上的整數。",
            ),
        ):
            resp = self._put(self.bid, self._step(self.pid, "/sell-ways"), {"sell_ways": rows})
            self.assertEqual(resp.status_code, 400, rows)
            self.assertIn(message, resp.json()["error"])
        saved = self._sell_ways(self.bid, self.pid, [{"name": "單盒", "price": 399}])
        self.assertEqual(saved["sell_ways"][0]["source"], "saved")
        self.assertEqual(self._get(self.bid, self._step(self.pid))["step"], 5)


# ---------------------------------------------------------------------------
# Sell-way numbers (computed by the program)
# ---------------------------------------------------------------------------


class SellWayNumbersTest(_Base):
    def test_single_and_three_pack_numbers_and_offers(self):
        bid = self._brand()
        bi_repo.save_brand_policies(
            web.conn, bid, [{"key": "ship_threshold", "params": {"threshold": 999}}], actor=ACTOR
        )
        pid = self._new_product(bid, "綜合維他命軟糖", page_url="https://shop.example/vit")
        data = self._sell_ways(
            bid,
            pid,
            [
                {"name": "單盒", "price": 399, "cost": 90, "shipping": 60},
                {
                    "name": "三盒組",
                    "components": [{"base": "單盒", "qty": 3}],
                    "price": 999,
                    "shipping": 60,
                    "landing_url": "https://shop.example/vit3",
                },
            ],
        )
        single, three = data["sell_ways"]
        self.assertEqual(
            (single["name"], single["shape"], single["components"], single["price"],
             single["list_price"], single["used_by"]),
            ("單盒", "base", [], 399.0, None, ["三盒組"]),
        )
        self.assertEqual(
            (single["break_even"], single["cap_per_sale"], single["cap_is_default"]),
            (249.0, 249.0, True),
        )
        self.assertEqual(
            (single["offer_labels"], single["offer_notes"]),
            ([], ["售價未滿 NT$999，不適用滿額免運"]),
        )
        self.assertEqual(
            (single["landing_url"], single["landing_is_default"]),
            ("https://shop.example/vit", True),
        )
        self.assertEqual(
            (three["list_price"], three["list_price_derived"], three["list_price_note"]),
            (1197.0, True, "推算：單盒 399 × 3"),
        )
        self.assertEqual(
            (three["cost"], three["cost_derived"], three["cost_note"], three["cost_estimate"]),
            (270.0, True, "推算：單盒 90 × 3", 270.0),
        )
        self.assertEqual((three["price"], three["price_derived"]), (999.0, False))
        self.assertEqual((three["break_even"], three["break_even_derived"]), (999 - 270 - 60, True))
        self.assertEqual(three["offer_labels"], ["組合價 省 198", "滿 NT$999 免運"])
        self.assertEqual(three["offer_sentences"], ["優惠價 NT$999（原價 NT$1,197）"])
        self.assertEqual(three["offer_notes"], [])
        self.assertEqual(
            (three["landing_url"], three["landing_is_default"]),
            ("https://shop.example/vit3", False),
        )
        self.assertEqual(
            (three["shape"], three["components"], three["used_by"]),
            ("composed",
             [{"sell_way_id": single["id"], "name": "單盒", "qty": 3, "price": 399.0,
               "cost": 90.0}],
             []),
        )

        again = self._sell_ways(
            bid,
            pid,
            [
                {
                    "id": single["id"],
                    "name": "單盒",
                    "price": 399,
                    "cost": 90,
                    "shipping": 60,
                    "cap_per_sale": 150,
                    "assumptions": ["cost"],
                }
            ],
        )
        [row] = again["sell_ways"]
        self.assertEqual(
            (row["cap_per_sale"], row["cap_is_default"], row["assumptions"]),
            (150.0, False, ["cost"]),
        )
        three_row = bi_repo.get_product(web.conn, bid, three["id"])
        assert three_row is not None
        self.assertEqual(three_row["status"], "archived")  # left out of the full list

    def _b1(self, bid: str, pid: str, *, box_cost=50, free=False) -> dict:
        """Drill 10 B1: 體驗包 (100 / 25) created first, 單盒 (180 / 50), 12 盒 = 單盒 × 12 at
        1,980 with its cost left empty, 5 盒＋2 包 with everything left empty."""
        box = {"name": "單盒", "price": 180, "shipping": 60}
        if box_cost is not None:
            box["cost"] = box_cost
        return self._sell_ways(
            bid,
            pid,
            [
                {"name": "體驗包", "price": 100, "cost": 25, "shipping": 35},
                box,
                {
                    "name": "12 盒",
                    "components": [{"base": "單盒", "qty": 12}],
                    "price": 1980,
                    "shipping": 60,
                    "free_shipping": free,
                },
                {
                    "name": "5 盒＋2 包",
                    "components": [{"base": "單盒", "qty": 5}, {"base": "體驗包", "qty": 2}],
                    "shipping": 60,
                },
            ],
        )

    def test_b1_twelve_boxes_cost_comes_from_its_own_base(self):
        bid = self._brand()
        pid = self._new_product(bid, "能量軟糖")
        rows = {r["name"]: r for r in self._b1(bid, pid)["sell_ways"]}
        self.assertEqual(list(rows), ["體驗包", "單盒", "12 盒", "5 盒＋2 包"])
        twelve = rows["12 盒"]
        # The step-4 GET row of 「12 盒」 (evidence for the issue's Verify).
        self.assertEqual(
            {k: twelve[k] for k in (
                "price", "price_derived", "price_note", "list_price", "list_price_derived",
                "list_price_note", "cost", "cost_derived", "cost_note", "cost_estimate",
                "cost_missing", "shipping", "free_shipping", "break_even", "break_even_derived",
                "offer_sentences", "offer_labels")},
            {
                "price": 1980.0, "price_derived": False, "price_note": "",
                "list_price": 2160.0, "list_price_derived": True,
                "list_price_note": "推算：單盒 180 × 12",
                "cost": 600.0, "cost_derived": True, "cost_note": "推算：單盒 50 × 12",
                "cost_estimate": 600.0, "cost_missing": [],
                "shipping": 60.0, "free_shipping": False,
                "break_even": 1980.0 - 600 - 60, "break_even_derived": True,
                "offer_sentences": ["優惠價 NT$1,980（原價 NT$2,160）"],
                "offer_labels": ["組合價 省 180"],
            },
        )
        mix = rows["5 盒＋2 包"]
        self.assertEqual(
            (mix["cost"], mix["cost_note"]), (300.0, "推算：單盒 50 × 5 ＋ 體驗包 25 × 2")
        )
        self.assertEqual(
            (mix["price"], mix["price_derived"], mix["price_note"]),
            (1100.0, True, "推算：單盒 180 × 5 ＋ 體驗包 100 × 2"),
        )
        self.assertEqual(mix["break_even"], 1100.0 - 300 - 60)
        self.assertEqual(rows["單盒"]["used_by"], ["12 盒", "5 盒＋2 包"])
        self.assertEqual(rows["體驗包"]["used_by"], ["5 盒＋2 包"])
        # The picker names the derived fields too.
        options = self.client.get(f"/api/ads/brands/{bid}/new-campaign/options")
        self.assertEqual(options.status_code, 200, options.text)
        self.assertEqual(options.json()["products"], [])  # not finished yet: nothing pickable
        self._group(bid, pid)
        self.client.post(self._url(bid, self._step(pid, "/complete")))
        picker = {
            o["display_name"]: o
            for o in self.client.get(f"/api/ads/brands/{bid}/new-campaign/options").json()[
                "products"
            ]
        }
        self.assertEqual(picker["12 盒"]["derived_fields"], ["list_price", "unit_variable_cost"])
        self.assertEqual(picker["單盒"]["derived_fields"], [])

    def test_unknown_base_cost_is_named_and_a_typed_cost_shows_the_estimate(self):
        bid = self._brand()
        pid = self._new_product(bid, "能量軟糖")
        rows = {r["name"]: r for r in self._b1(bid, pid, box_cost=None)["sell_ways"]}
        twelve = rows["12 盒"]
        self.assertEqual((twelve["cost"], twelve["cost_derived"], twelve["break_even"]),
                         (None, False, None))
        self.assertEqual(twelve["cost_missing"], [{"sell_way_id": rows["單盒"]["id"],
                                                   "name": "單盒"}])
        self.assertIsNone(twelve["cost_estimate"])
        typed = self._b1(bid, pid)  # 單盒 cost 50 now; 12 盒 typed 560 below
        body = [
            {k: r[k] for k in ("id", "name", "price", "shipping")}
            | ({"cost": r["cost"]} if r["shape"] == "base" else {})
            | ({"components": [{"base": c["name"], "qty": c["qty"]} for c in r["components"]]}
               if r["shape"] == "composed" else {})
            for r in typed["sell_ways"]
        ]
        body[2]["cost"] = 560
        body[3].pop("price")
        rows = {r["name"]: r for r in self._sell_ways(bid, pid, body)["sell_ways"]}
        self.assertEqual(
            (rows["12 盒"]["cost"], rows["12 盒"]["cost_derived"], rows["12 盒"]["cost_estimate"]),
            (560.0, False, 600.0),
        )
        self.assertEqual(rows["12 盒"]["break_even_derived"], False)

    def test_free_shipping_sentence_and_store_policy(self):
        bid = self._brand()
        bi_repo.save_brand_policies(
            web.conn, bid, [{"key": "ship_threshold", "params": {"threshold": 999}}], actor=ACTOR
        )
        pid = self._new_product(bid, "能量軟糖")
        rows = {r["name"]: r for r in self._b1(bid, pid, free=True)["sell_ways"]}
        twelve = rows["12 盒"]
        self.assertTrue(twelve["free_shipping"])
        self.assertEqual(twelve["offer_sentences"],
                         ["優惠價 NT$1,980（原價 NT$2,160）", "這組免運"])
        # Its own 「這組免運」 replaces the store-wide 滿 NT$999 免運 it also reaches.
        self.assertEqual(twelve["offer_labels"], ["組合價 省 180", "這組免運"])
        self.assertEqual(twelve["offer_notes"], [])
        sources = bi_repo.offer_sources(web.conn, bid, twelve["id"])
        self.assertEqual([s["sentence"] for s in sources if s["offer_key"] == "free_shipping"],
                         ["這組免運"])
        self.assertIn("free_shipping", bi_repo.available_offer_keys(web.conn, bid, twelve["id"]))
        self.assertEqual(rows["5 盒＋2 包"]["offer_labels"], ["滿 NT$999 免運"])

    def test_archive_guard_keeps_a_base_a_composed_sell_way_uses(self):
        bid = self._brand()
        pid = self._new_product(bid, "能量軟糖")
        rows = self._b1(bid, pid)["sell_ways"]
        trial = rows[0]
        body = [
            {"id": r["id"], "name": r["name"], "price": r["price"]}
            | ({"components": [{"base": c["name"], "qty": c["qty"]} for c in r["components"]]}
               if r["shape"] == "composed" else {})
            for r in rows
            if r["name"] != "體驗包"
        ]
        resp = self._put(bid, self._step(pid, "/sell-ways"), {"sell_ways": body})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "「體驗包」還在「5 盒＋2 包」裡，先從組合拿掉。")
        self.assertEqual(bi_repo.get_product(web.conn, bid, trial["id"])["status"], "active")
        # Leaving the composed one out too archives both.
        kept = self._sell_ways(bid, pid, body[:2])["sell_ways"]
        self.assertEqual([r["name"] for r in kept], ["單盒", "12 盒"])
        self.assertEqual(bi_repo.get_product(web.conn, bid, trial["id"])["status"], "archived")
        # A base never turns into a composed sell-way (and back).
        resp = self._put(bid, self._step(pid, "/sell-ways"), {"sell_ways": [
            {"id": kept[0]["id"], "name": "單盒", "price": 180},
            {"id": kept[1]["id"], "name": "12 盒", "price": 1980},
        ]})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("基本賣法和組合", resp.json()["error"])

    def test_ai_proposals_qty_n_is_composed_of_the_one_unit_proposal(self):
        bid = self._brand()
        pid = self._new_product(bid, "能量軟糖", page_url="https://shop.example/e")
        ir.save_product_prefill(web.conn, bid, pid, status="done", prefill_json={
            "sell_ways": [
                {"name": "三盒組", "qty": 3, "price": 499, "list_price": 540, "note": "商品頁"},
                {"name": "單盒", "qty": 1, "price": 180, "list_price": None, "note": "商品頁"},
            ]
        })
        three, box = self._get(bid, self._step(pid, "/sell-ways"))["sell_ways"]
        self.assertEqual((box["shape"], box["components"], box["source"]), ("base", [], "ai"))
        self.assertEqual(
            (three["shape"], three["components"], three["price"], three["list_price"]),
            ("composed",
             [{"sell_way_id": None, "name": "單盒", "qty": 3, "price": 180.0, "cost": None}],
             499.0, 540.0),
        )
        # Without a one-unit proposal a qty-N proposal stays a base.
        ir.save_product_prefill(web.conn, bid, pid, status="done", prefill_json={
            "sell_ways": [{"name": "三盒組", "qty": 3, "price": 499, "note": "商品頁"}]
        })
        [alone] = self._get(bid, self._step(pid, "/sell-ways"))["sell_ways"]
        self.assertEqual((alone["shape"], alone["components"]), ("base", []))

    def test_lead_brand_sees_close_rate_in_break_even(self):
        bid = self._brand()
        bi_repo.set_brand_switches(
            web.conn, bid, market_region=None, conversion_goal="lead", actor=ACTOR
        )
        pid = self._new_product(bid, "健身體驗課")
        data = self._sell_ways(
            bid,
            pid,
            [
                {
                    "name": "單堂",
                    "price": 1000,
                    "cost": 200,
                    "shipping": 0,
                    "close_rate": 20,
                }
            ],
        )
        self.assertTrue(data["show_close_rate"])
        self.assertEqual(data["assumptions"]["close_rate"]["value"], 20)
        [row] = data["sell_ways"]
        # Stored as typed (20 = 20%); break-even (1000 - 200) x rate_fraction(20) = 160.
        self.assertEqual((row["close_rate"], row["break_even"]), (20.0, 160.0))

    def test_refusals_are_keyed_by_row_and_field(self):
        """F50 Contract I (F50-I04): step 4 keeps no rule of its own -- it sends what was typed (a
        blank price is null, a quantity is its text) and the PUT refuses every bad field at once,
        keyed `sell_ways.{i}.{field}`, with the one input-rule sentence; nothing is saved."""
        bid = self._brand()
        bi_repo.set_brand_switches(
            web.conn, bid, market_region=None, conversion_goal="lead", actor=ACTOR
        )
        pid = self._new_product(bid, "健身體驗課")
        percent = "「單堂」的成交率要大於 0、最多 100（填 20 代表 20%）。"
        for rows, field_errors in (
            ([{"name": "單堂", "price": None}], {"sell_ways.0.price": "「單堂」的售價請填數字。"}),
            ([{"name": "單堂", "price": 0, "close_rate": 0}],
             {"sell_ways.0.price": "「單堂」的售價要大於 0。", "sell_ways.0.close_rate": percent}),
            ([{"name": "單堂", "price": 1000, "close_rate": 120}],
             {"sell_ways.0.close_rate": percent}),
            ([{"name": "單堂", "price": 1000, "list_price": 900}],
             {"sell_ways.0.list_price": "售價（1000）不能大於原價（900）。"}),
            ([{"name": "單堂", "price": 1000},
              {"name": "五堂", "components": [{"base": "單堂", "qty": "x"}]}],
             {"sell_ways.1.components.0.qty": "「五堂」裡「單堂」的數量要是 1 以上的整數。"}),
        ):
            resp = self._put(bid, self._step(pid, "/sell-ways"), {"sell_ways": rows})
            self.assertEqual(resp.status_code, 400, rows)
            body = resp.json()
            self.assertEqual(body["field_errors"], field_errors)
            self.assertEqual(body["error"], next(iter(field_errors.values())))
        self.assertEqual(bi_repo.list_sell_ways(web.conn, bid, pid), [])
        # A quantity typed as text is the server's to parse.
        saved = self._sell_ways(bid, pid, [
            {"name": "單堂", "price": 1000},
            {"name": "五堂", "components": [{"base": "單堂", "qty": "5"}]},
        ])
        self.assertEqual(saved["sell_ways"][1]["components"][0]["qty"], 5)

    def test_assumed_cost_is_derived_by_the_server(self):
        """「空著的成本填參考值」 (F50-I04): a base row flagged `assumptions: ["cost"]` with an
        empty cost is stored with whole(price x (100 - 45) / 100) -- the benchmark margin -- and
        returned flagged; the browser never multiplies. A composed row's cost stays its bases'."""
        bid = self._brand()
        pid = self._new_product(bid)
        data = self._sell_ways(bid, pid, [
            {"name": "單盒", "price": 1280, "cost": None, "assumptions": ["cost"]},
            {"name": "三盒組", "components": [{"base": "單盒", "qty": 3}], "price": 3500,
             "assumptions": ["cost"]},
        ])
        single, three = data["sell_ways"]
        self.assertEqual((single["cost"], single["assumptions"]), (704.0, ["cost"]))
        self.assertEqual((three["cost"], three["cost_derived"], three["assumptions"]),
                         (2112.0, True, []))
        # Saved back with the number it now holds, the flag and the value stay.
        again = self._sell_ways(bid, pid, [
            {"id": single["id"], "name": "單盒", "price": 1280, "cost": 704,
             "assumptions": ["cost"]},
        ])["sell_ways"][0]
        self.assertEqual((again["cost"], again["assumptions"]), (704.0, ["cost"]))


# ---------------------------------------------------------------------------
# 完成, bundles, tenancy
# ---------------------------------------------------------------------------


class CompleteBundleTenancyTest(_Base):
    def test_complete_refused_before_the_sell_ways_step_then_done(self):
        bid = self._brand()
        pid = self._new_product(bid)
        resp = self.client.post(self._url(bid, self._step(pid, "/complete")))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("商品是什麼", resp.json()["error"])
        self._sell_ways(bid, pid, [{"name": "單盒", "price": 399}])
        # F50 Contract R: zero customer groups is not ready -> 完成 is refused with its sentence
        resp = self.client.post(self._url(bid, self._step(pid, "/complete")))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "至少要有一群顧客才能完成商品建檔。")
        status = self._get(bid, self._step(pid))
        self.assertFalse(status["ready"])
        self.assertEqual(status["checklist"], [
            {"key": "groups", "label": "誰會買", "ok": False, "required": True},
            {"key": "proof", "label": "證據與說法", "ok": False, "required": False},
            {"key": "sell_ways", "label": "賣法與價格", "ok": True, "required": True},
        ])
        self._group(bid, pid)
        data = self.client.post(self._url(bid, self._step(pid, "/complete"))).json()["data"]
        self.assertEqual((data["step"], data["completed"], data["ready"]), (5, True, True))
        self.assertTrue(all(c["ok"] for c in data["checklist"] if c["required"]))
        # re-entry edits in place: a step PUT does not reopen the product
        self._group(bid, pid, "運動族")
        self.assertTrue(self._get(bid, self._step(pid))["completed"])
        # a finished product keeps at least one group
        resp = self._put(bid, self._step(pid, "/who"), {"groups": []})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "至少留一群顧客；不賣給任何人就先封存這個商品。")
        self.assertEqual([g["who"] for g in self._get(bid, self._step(pid, "/who"))["groups"]],
                         ["運動族"])

    def test_complete_refused_when_every_sell_way_is_gone(self):
        bid = self._brand()
        pid = self._new_product(bid)
        [row] = self._sell_ways(bid, pid, [{"name": "單盒", "price": 399}])["sell_ways"]
        bi_repo.update_product(
            web.conn, bid, row["id"], name="綜合維他命軟糖 · 單盒", status="archived", actor=ACTOR
        )
        resp = self.client.post(self._url(bid, self._step(pid, "/complete")))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("至少要有一種賣法", resp.json()["error"])

    def test_bundle_create_edit_reused_and_validation(self):
        bid = self._brand()
        vit = self._finished(bid, "綜合維他命軟糖")
        pro = self._finished(bid, "益生菌軟糖", price=459, cost=110)
        self._ok_put(
            bid,
            self._step(pro, "/who"),
            {"groups": [{"who": "腸胃敏感族", "pain_keys": ["experience"]}]},
        )
        draft = self._new_product(bid, "魚油膠囊")
        self._sell_ways(bid, draft, [{"name": "單瓶", "price": 500}])  # 完成 not pressed
        other_bid = self._brand()
        foreign = self._finished(other_bid, "別人的商品")
        vit_box, pro_box = self._base(bid, vit), self._base(bid, pro)
        vit_three = self._sell_ways(bid, vit, [
            {"id": vit_box, "name": "單盒", "price": 399, "cost": 90, "shipping": 60},
            {"name": "三盒", "components": [{"base": "單盒", "qty": 3}], "price": 999},
        ])["sell_ways"][1]["id"]
        body = {
            "name": "雙效組",
            "components": [{"sell_way_id": vit_box, "qty": 1}, {"sell_way_id": pro_box, "qty": 1}],
            "price": 799,
            "shipping": 60,
        }
        for components, message in (
            ([{"sell_way_id": vit_box, "qty": 1}], "至少要放兩個"),
            ([{"sell_way_id": vit_box, "qty": 2}], "至少要放兩個"),  # one product: its step 4
            ([{"sell_way_id": vit_box, "qty": 1},
              {"sell_way_id": self._base(other_bid, foreign), "qty": 1}], "找不到的賣法"),
            ([{"sell_way_id": vit_box, "qty": 1}, {"sell_way_id": pro, "qty": 1}], "找不到的賣法"),
            ([{"sell_way_id": vit_three, "qty": 1}, {"sell_way_id": pro_box, "qty": 1}],
             "找不到的賣法"),  # a composed sell-way is not a component
            ([{"sell_way_id": vit_box, "qty": 1},
              {"sell_way_id": self._base(bid, draft, "單瓶"), "qty": 1}], "還沒建完"),
        ):
            resp = self.client.post(
                self._url(bid, "/bundles"), json={**body, "components": components}
            )
            self.assertEqual(resp.status_code, 400, components)
            self.assertIn(message, resp.json()["error"])
        created = self.client.post(self._url(bid, "/bundles"), json=body).json()["data"]
        self.assertEqual(
            (created["list_price"], created["list_price_note"], created["cost"]),
            (858.0, "推算：綜合維他命軟糖・單盒 399 × 1 ＋ 益生菌軟糖・單盒 459 × 1", 200.0),
        )
        self.assertEqual(
            (created["break_even"], created["offer_labels"]), (539.0, ["組合價 省 59"])
        )
        self.assertEqual(created["offer_sentences"], ["優惠價 NT$799（原價 NT$858）"])
        self.assertEqual(
            [(c["sell_way_id"], c["product_id"], c["product_name"], c["name"], c["unit_price"],
              c["unit_cost"]) for c in created["components"]],
            [(vit_box, vit, "綜合維他命軟糖", "單盒", 399.0, 90.0),
             (pro_box, pro, "益生菌軟糖", "單盒", 459.0, 110.0)],
        )
        self.assertEqual(
            bi_repo.knowledge_product_ids(web.conn, bid, created["id"]), [vit, pro]
        )
        # every component product's groups, in component order (each finished product has one)
        self.assertEqual([g["pain_labels"] for g in created["reused"]["groups"]],
                         [["太麻煩"], ["用起來不舒服"]])
        edited = self._ok_put(
            bid,
            f"/bundles/{created['id']}",
            {
                **body,
                "components": [{"sell_way_id": vit_box, "qty": 2},
                               {"sell_way_id": pro_box, "qty": 1}],
                "price": 1099,
            },
        )
        self.assertEqual(
            (edited["id"], edited["list_price"], edited["cost"]), (created["id"], 1257.0, 290.0)
        )
        self.assertEqual(self._get(bid, f"/bundles/{created['id']}")["price"], 1099.0)

    def _stored(self, bid: str) -> tuple:
        """Everything a bundle save writes, as the facade reads it: product rows, sell-ways with
        their components, and each row's economics."""
        products = sorted(p["id"] for p in bi_repo.all_product_rows(web.conn, bid))
        ways = [(w["id"], w["components"]) for w in bi_repo.list_sell_ways(web.conn, bid)]
        econ = {
            pid: (e or {}).get("id")
            for pid in products
            for e in [bi_repo.get_product_economics(web.conn, bid, pid, raw=True)]
        }
        return products, ways, econ

    def test_bundle_preview_computes_like_a_saved_bundle_and_writes_nothing(self):
        bid = self._brand()
        vit = self._finished(bid, "綜合維他命軟糖")
        pro = self._finished(bid, "益生菌軟糖", price=459, cost=110)
        self._ok_put(
            bid,
            self._step(pro, "/who"),
            {"groups": [{"who": "腸胃敏感族", "pain_keys": ["experience"]}]},
        )
        other_bid = self._brand()
        foreign = self._base(other_bid, self._finished(other_bid, "別人的商品"))
        vit_box, pro_box = self._base(bid, vit), self._base(bid, pro)
        body = {
            "name": "雙效組",
            "components": [{"sell_way_id": vit_box, "qty": 1}, {"sell_way_id": pro_box, "qty": 1}],
            "price": 799,
            "shipping": 60,
        }
        before = self._stored(bid)

        resp = self.client.post(self._url(bid, "/bundles/preview"), json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        preview = resp.json()["data"]
        self.assertIsNone(preview["id"])
        self.assertEqual(
            (preview["list_price"], preview["list_price_note"], preview["cost"]),
            (858.0, "推算：綜合維他命軟糖・單盒 399 × 1 ＋ 益生菌軟糖・單盒 459 × 1", 200.0),
        )
        self.assertEqual(
            (preview["break_even"], preview["cap_per_sale"], preview["offer_labels"]),
            (539.0, 539.0, ["組合價 省 59"]),
        )
        self.assertEqual(
            [(c["product_name"], c["unit_price"], c["unit_cost"]) for c in preview["components"]],
            [("綜合維他命軟糖", 399.0, 90.0), ("益生菌軟糖", 459.0, 110.0)],
        )
        self.assertEqual([g["who"] for g in preview["reused"]["groups"]], ["上班族", "腸胃敏感族"])
        self.assertFalse(preview["show_close_rate"])
        self.assertIn("shipping_cost", preview["benchmarks"])
        # Nothing was written: no product / component / economics row, no bundle on the page.
        self.assertEqual(self._stored(bid), before)
        self.assertEqual(self._get(bid, "/products")["bundles"], [])

        for components, message in (
            ([{"sell_way_id": vit_box, "qty": 1}], "至少要放兩個"),
            ([{"sell_way_id": vit_box, "qty": 1}, {"sell_way_id": foreign, "qty": 1}],
             "找不到的賣法"),
        ):
            resp = self.client.post(
                self._url(bid, "/bundles/preview"), json={**body, "components": components}
            )
            self.assertEqual(resp.status_code, 400, components)
            self.assertIn(message, resp.json()["error"])
        self.assertEqual(self._stored(bid), before)

        # The same body then creates the bundle the preview showed (the name is still free).
        created = self.client.post(self._url(bid, "/bundles"), json=body).json()["data"]
        self.assertEqual({**preview, "id": created["id"]}, created)

    def test_other_org_gets_404_everywhere(self):
        bid = self._brand()
        pid = self._finished(bid, "綜合維他命軟糖")
        headers = self._other_org_headers()
        for path in (
            "/products",
            self._step(pid),
            self._step(pid, "/what"),
            self._step(pid, "/who"),
            self._step(pid, "/evidence"),
            self._step(pid, "/sell-ways"),
        ):
            self.assertEqual(
                self.client.get(self._url(bid, path), headers=headers).status_code, 404, path
            )
        for path in ("/what", "/who", "/evidence", "/sell-ways"):
            resp = self.client.put(self._url(bid, self._step(pid, path)), json={}, headers=headers)
            self.assertEqual(resp.status_code, 404, path)
        for path in ("/products", "/bundles", "/bundles/preview", self._step(pid, "/complete")):
            resp = self.client.post(self._url(bid, path), json={"name": "x"}, headers=headers)
            self.assertEqual(resp.status_code, 404, path)

    def test_product_of_another_brand_is_404(self):
        bid, other = self._brand(), self._brand()
        pid = self._new_product(other, "別人的商品")
        self.assertEqual(self.client.get(self._url(bid, self._step(pid, "/what"))).status_code, 404)
        resp = self._put(
            bid, self._step(pid, "/sell-ways"), {"sell_ways": [{"name": "單盒", "price": 1}]}
        )
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
