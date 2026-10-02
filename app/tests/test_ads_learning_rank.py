"""app/tests/test_ads_learning_rank.py — F46-I04 Contract B falsifiers for the one ranking rule
(pure, no database): the drill-10 P1 shape (nothing under the cap -> the 555 winner is kept
relative, 1,643 and 1,769 are replaced), a winner under the cap with 4 sales is kept and flagged
樣本少, ties, no cap, no sales, and rows that are not ranked at all; plus the stored scope's
round trip.
"""

import unittest

from app.ads import learning_rank


def _row(name, spend, results, *, cap=450.0, currency="TWD"):
    return {"name": name, "spend": spend, "results": results, "cap": cap, "currency": currency}


class DrillTenShapeTest(unittest.TestCase):
    def test_nothing_under_the_cap_keeps_the_best_and_those_within_thirty_percent(self):
        ranked = learning_rank.rank([
            _row("通勤族・下班後加班", 3538.0, 2),  # 1,769
            _row("考前一週・書包一盒", 3330.0, 6),  # 555
            _row("通勤族・地鐵十分鐘", 3286.0, 2),  # 1,643
        ])
        self.assertEqual(
            [(r["name"], r["rank"], r["of"], r["verdict"]) for r in ranked],
            [("考前一週・書包一盒", 1, 3, "keep_relative"),
             ("通勤族・地鐵十分鐘", 2, 3, "replace"),
             ("通勤族・下班後加班", 3, 3, "replace")],
        )
        self.assertEqual(ranked[0]["cost_per_sale"], 555.0)
        self.assertEqual(ranked[0]["verdict_label"], "留下")
        self.assertEqual(ranked[0]["flags"], ["相對最好，仍高於上限"])
        self.assertEqual(ranked[1]["flags"], ["樣本少"])
        self.assertEqual(ranked[1]["verdict_label"], "換掉")
        self.assertEqual(
            learning_rank.rule_text(ranked, 450.0),
            "沒有一則低於上限 450 → 留下最好的 555 和 722 以內的；其餘換掉",
        )

    def test_a_winner_under_the_cap_with_four_sales_is_kept_and_flagged_few(self):
        ranked = learning_rank.rank([
            _row("備考生・讀到深夜", 1160.0, 4),  # 290
            _row("考前一週・書包一盒", 3330.0, 6),  # 555: within 1.3 × 290? no (377)
            _row("會議前・午休五分鐘", 1420.0, 0),
        ])
        self.assertEqual(
            [(r["name"], r["verdict"], r["flags"]) for r in ranked],
            [("備考生・讀到深夜", "keep", ["樣本少"]),
             ("考前一週・書包一盒", "replace", []),
             ("會議前・午休五分鐘", "replace", [])],
        )
        self.assertTrue(ranked[0]["few"])
        self.assertIsNone(ranked[2]["cost_per_sale"])
        self.assertEqual(
            learning_rank.rule_text(ranked, 450.0), "1 則每筆低於上限 450 → 留下；其餘換掉",
        )


class OrderAndEdgeTest(unittest.TestCase):
    def test_equal_cost_ranks_more_sales_first_then_name(self):
        ranked = learning_rank.rank([
            _row("c", 1000.0, 5), _row("a", 2000.0, 10), _row("b", 1000.0, 5),
        ])
        # All three cost 200: 10 sales first, then name.
        self.assertEqual([r["name"] for r in ranked], ["a", "b", "c"])
        self.assertEqual([r["verdict"] for r in ranked], ["keep", "keep", "keep"])
        self.assertEqual([r["flags"] for r in ranked], [[], [], []])

    def test_unsold_rows_follow_the_sold_ones_cheapest_spend_first(self):
        ranked = learning_rank.rank([
            _row("沒賣大", 900.0, 0), _row("賣", 400.0, 1), _row("沒賣小", 300.0, 0),
        ])
        self.assertEqual([r["name"] for r in ranked], ["賣", "沒賣小", "沒賣大"])
        self.assertEqual([r["verdict"] for r in ranked], ["keep", "replace", "replace"])

    def test_no_cap_uses_the_relative_rule_and_says_so(self):
        ranked = learning_rank.rank([
            _row("A", 1000.0, 10, cap=None), _row("B", 1250.0, 10, cap=None),
            _row("C", 1400.0, 10, cap=None),
        ])
        self.assertEqual([r["verdict"] for r in ranked], ["keep_relative", "keep_relative",
                                                          "replace"])
        self.assertEqual(ranked[0]["flags"], ["相對最好"])
        self.assertEqual(
            learning_rank.rule_text(ranked, None),
            "沒有上限 → 留下最好的 100 和 130 以內的；其餘換掉",
        )

    def test_no_sold_row_replaces_everything(self):
        ranked = learning_rank.rank([_row("A", 500.0, 0), _row("B", 200.0, 0)])
        self.assertEqual([r["verdict"] for r in ranked], ["replace", "replace"])
        self.assertEqual(learning_rank.rule_text(ranked, 450.0), "沒有一則賣出 → 全部換掉")

    def test_unknown_rows_are_not_ranked(self):
        ranked = learning_rank.rank([
            _row("結果不明", 500.0, None), _row("花費不明", None, 3),
            _row("兩種幣別", 500.0, 3, currency=None), _row("沒花錢", 0.0, 0),
            _row("算數", 300.0, 1),
        ])
        self.assertEqual([(r["name"], r["rank"], r["of"]) for r in ranked], [("算數", 1, 1)])
        self.assertIsNone(learning_rank.rule_text([], 450.0))


class ScopeRoundTripTest(unittest.TestCase):
    def test_scope_parses_back_and_old_rows_do_not(self):
        (row,) = learning_rank.rank([_row("A", 3330.0, 6)])
        keys = {"audience": "cold", "pain": "late", "angle": "box", "hook": "h", "proof": "none",
                "offer": "bundle", "format": "single_image"}
        text = learning_rank.scope(row, keys, "pcg_1")
        self.assertEqual(
            text,
            "coord；v=2；verdict=keep_relative；rank=1；of=1；sales=6；spend=3330；cpr=555；cap=450"
            "；few=0；group=pcg_1；audience=cold；pain=late；angle=box；hook=h；proof=none"
            "；offer=bundle；format=single_image；cur=TWD",
        )
        parsed = learning_rank.parse_scope(text)
        assert parsed is not None
        self.assertEqual(
            {k: parsed[k] for k in ("verdict", "rank", "of", "sales", "spend", "cost_per_sale",
                                    "cap", "few", "customer_group_id", "currency", "flags")},
            {"verdict": "keep_relative", "rank": 1, "of": 1, "sales": 6, "spend": 3330,
             "cost_per_sale": 555, "cap": 450, "few": False, "customer_group_id": "pcg_1",
             "currency": "TWD", "flags": ["相對最好，仍高於上限"]},
        )
        self.assertEqual(parsed["keys"]["proof"], "none")
        self.assertIsNone(learning_rank.parse_scope(
            "coord；grade=on_target；cpr=50；cap=100；audience=a；pain=p；angle=g；hook=h"
            "；proof=r；offer=o；format=f",
        ))
        self.assertIsNone(learning_rank.parse_scope("ads;campaign=x"))


if __name__ == "__main__":
    unittest.main()
