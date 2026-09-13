"""app/tests/test_product_hierarchy.py — F05-I02: knowledge lives on the mother product
(ARCHITECTURE.md §8 item 1). `context_compiler.compile()` resolves a sell way's `product_id`
through `bi_repo.knowledge_product_id()` before reading facts, so a sell way with no facts of
its own still gets the mother product's confirmed facts in the prompt text.

This file does not belong to any managed module, so it must not import `app.ads.*` or
`app.workbench.*` internals (the architecture checker would flag it) — only `context_compiler`
and the shared `brand_intelligence` repository.
"""

import unittest

import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.llm import context_compiler

ACTOR = "測試員"


class ContextCompilerFollowsMotherProductTest(unittest.TestCase):
    def setUp(self):
        self.brand = bi_repo.create_brand(
            web.conn, org_id=coredb.DEV_ORG_ID, name="測試品牌：知識掛母產品", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        self.mother = bi_repo.create_product(web.conn, self.brand_id, name="薑黃錠", actor=ACTOR)
        self.sell_way = bi_repo.create_product(
            web.conn, self.brand_id, name="薑黃錠 · 單瓶", actor=ACTOR,
            parent_id=self.mother["id"],
        )
        bi_repo.create_product_fact(
            web.conn, self.brand_id, self.mother["id"], actor=ACTOR, fact_type="ingredient",
            label="主成分", value="薑黃萃取物", status="confirmed", confirmed_by=ACTOR,
        )

    def test_compile_on_sell_way_includes_mother_products_facts(self):
        text, _ids, _bv, _pv = context_compiler.compile(
            web.conn, self.brand_id, self.sell_way["id"])
        self.assertIn("薑黃萃取物", text)

    def test_compile_on_mother_product_still_includes_its_own_facts(self):
        text, _ids, _bv, _pv = context_compiler.compile(
            web.conn, self.brand_id, self.mother["id"])
        self.assertIn("薑黃萃取物", text)


if __name__ == "__main__":
    unittest.main()
