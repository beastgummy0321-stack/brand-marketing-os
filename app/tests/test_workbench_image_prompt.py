"""app/tests/test_workbench_image_prompt.py — F07-I06: the image-prompt tables (`visual.py`) and
their program-side checks (`validate.check_image_reply`/`trim_image_reply`), proven on recorded
probe outputs (`.harness/scratch/probes/image-prompt-v2/`, `image-prompt-v4/`). Pure-function
tests only, no DB, no model call — CI never calls a model (ARCHITECTURE.md §5.8).

This file is workbench code (ARCHITECTURE.md §2), so it obeys `workbench.may_depend_on == []`.
The 2026-09-09 renderer tests (`render_hero_prompt` and friends, `_output_line`, `_product_line`)
retire here — F07-I07 retires that code and tests the reference line instead.
"""

import copy
import json
import unittest
from pathlib import Path

from app.workbench import validate, visual

FIXTURES = Path(__file__).parent / "fixtures" / "workbench"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _allowed(task_key: str, subject_roles: list, offer_key, proof_key) -> dict:
    return {
        "subject_role": subject_roles,
        "persuasion": visual.allowed_persuasion(task_key, offer_key, proof_key),
    }


def _item_paths(results: list, i: int, *, include_repeat: bool = False) -> list:
    prefix = f"items[{i}]."
    out = []
    for r in results:
        if not r["path"].startswith(prefix):
            continue
        if include_repeat or not r["path"].endswith("headline_repeat"):
            out.append(r)
    return out


# -- fixture A：stop_relate（cold_unaware），10 項全綠 ------------------------------------

class FixtureATest(unittest.TestCase):
    def setUp(self):
        self.data = copy.deepcopy(_load("image_prompt_v2_A.json"))
        self.plan = [("brand_spec", "exploit")] * 10
        row = visual.task_row("cold_unaware", None)
        self.allowed = _allowed(row["key"], row["subject_roles"], "none", "none")
        self.leak_terms = visual.leak_terms(
            audience_label="陌生・不知有問題", task_label=row["label"],
        )
        self.quotable_text = "（無）\n每顆 150mg 咖啡因"

    def test_all_items_ok(self):
        validate.trim_image_reply(self.data, "single")
        results = validate.check_image_reply(
            self.data, shape="single", plan=self.plan, allowed=self.allowed, task_rows=None,
            leak_terms=self.leak_terms, quotable_text=self.quotable_text,
        )
        bad = [r for r in results if not r["ok"]]
        self.assertEqual(bad, [])


# -- fixture B：convert 型 allowed，含 mutation 系列 ---------------------------------------

class FixtureBTest(unittest.TestCase):
    def setUp(self):
        self.base = _load("image_prompt_v2_B.json")
        self.plan = [("brand_spec", "exploit")] * 10
        self.allowed = {
            "subject_role": ["clear", "hero"],
            "persuasion": ["none", "offer_headline", "price_breakdown", "countdown"],
        }
        self.leak_terms = []
        self.quotable_text = "滿799免運／限時9折到8/31／累計滿$3000送T-shirt\n每顆含有150mg咖啡因"

    def data(self):
        return copy.deepcopy(self.base)

    def check(self, data):
        return validate.check_image_reply(
            data, shape="single", plan=self.plan, allowed=self.allowed, task_rows=None,
            leak_terms=self.leak_terms, quotable_text=self.quotable_text,
        )

    def test_all_items_ok(self):
        data = self.data()
        validate.trim_image_reply(data, "single")
        results = self.check(data)
        bad = [r for r in results if not r["ok"]]
        self.assertEqual(bad, [])

    def test_eleven_items_trimmed_then_ok(self):
        data = self.data()
        data["items"].append(copy.deepcopy(data["items"][0]))
        self.assertEqual(len(data["items"]), 11)
        validate.trim_image_reply(data, "single")
        self.assertEqual(len(data["items"]), 10)
        bad = [r for r in self.check(data) if not r["ok"]]
        self.assertEqual(bad, [])

    def test_nine_items_round_fails(self):
        data = self.data()
        del data["items"][9]
        results = self.check(data)
        bad = {r["path"] for r in results if not r["ok"]}
        self.assertEqual(bad, {"items"})

    def test_headline_over_14_chars_fails_only_headline(self):
        data = self.data()
        old_headline = data["items"][0]["headline"][0]
        new_headline = "測" * 15
        data["items"][0]["headline"] = [new_headline]
        data["items"][0]["prompt"] = data["items"][0]["prompt"].replace(
            f"「{old_headline}」", f"「{new_headline}」", 1,
        )
        self._assert_only(data, 1, "headline")

    def test_item_device_outside_list_fails_only_device(self):
        data = self.data()
        data["items"][0]["device"] = "not_a_real_device"
        self._assert_only(data, 1, "device")

    def test_item_layout_outside_list_fails_only_layout(self):
        data = self.data()
        data["items"][0]["layout"] = "not_a_real_layout"
        self._assert_only(data, 1, "layout")

    def test_item_beyond_plan_length_gets_no_look(self):
        data = self.data()
        short_plan = [("brand_spec", "exploit")] * 9
        results = validate.check_image_reply(
            data, shape="single", plan=short_plan, allowed=self.allowed, task_rows=None,
            leak_terms=self.leak_terms, quotable_text=self.quotable_text,
        )
        look_results = [r for r in results if r["path"] == "items[10].look"]
        self.assertTrue(look_results and not look_results[0]["ok"], look_results)

    def test_unknown_device_not_counted_towards_devices_seen(self):
        data = self.data()
        known = ["contrast", "metaphor", "borrowed_format"]
        for i, item in enumerate(data["items"]):
            item["device"] = known[i % 3] if i < 9 else "not_a_real_device"
        results = self.check(data)
        devices_result = next(r for r in results if r["path"] == "items_devices")
        self.assertFalse(devices_result["ok"], devices_result)

    def test_exactly_four_devices_passes(self):
        data = self.data()
        devices4 = ["contrast", "metaphor", "borrowed_format", "frozen_moment"]
        for i, item in enumerate(data["items"]):
            item["device"] = devices4[i % 4]
        results = self.check(data)
        devices_result = next(r for r in results if r["path"] == "items_devices")
        self.assertTrue(devices_result["ok"], devices_result)

    def test_exactly_five_layouts_passes_four_fails(self):
        layouts5 = ["candid_scene", "portrait_focus", "subject_focus", "split_compare", "flat_lay"]

        data5 = self.data()
        for i, item in enumerate(data5["items"]):
            item["layout"] = layouts5[i % 5]
        results5 = self.check(data5)
        layouts_result5 = next(r for r in results5 if r["path"] == "items_layouts")
        self.assertTrue(layouts_result5["ok"], layouts_result5)

        data4 = self.data()
        layouts4 = layouts5[:4]
        for i, item in enumerate(data4["items"]):
            item["layout"] = layouts4[i % 4]
        results4 = self.check(data4)
        layouts_result4 = next(r for r in results4 if r["path"] == "items_layouts")
        self.assertFalse(layouts_result4["ok"], layouts_result4)

    def test_four_headlines_share_first_two_chars_not_flagged_at_prefix_length_three(self):
        data = self.data()
        heads = ["AB1同批", "AB2同批", "AB3同批", "AB4同批"]
        for i, new_headline in enumerate(heads):
            old_headline = data["items"][i]["headline"][0]
            data["items"][i]["headline"] = [new_headline]
            data["items"][i]["prompt"] = data["items"][i]["prompt"].replace(
                f"「{old_headline}」", f"「{new_headline}」", 1,
            )
        results = self.check(data)
        repeats = [r for r in results if r["path"].endswith("headline_repeat")]
        self.assertEqual(repeats, [])

    def test_headline_not_quoted_fails_only_headline(self):
        data = self.data()
        data["items"][0]["headline"] = ["完全不存在的字串"]
        self._assert_only(data, 1, "headline")

    def test_price_not_in_quotable_text_fails_only_numbers(self):
        data = self.data()
        data["items"][0]["prompt"] += "「NT$399」"
        self._assert_only(data, 1, "prompt_numbers")

    def test_countdown_not_in_quotable_text_fails_only_numbers(self):
        data = self.data()
        data["items"][0]["prompt"] += "「00:07:31」"
        self._assert_only(data, 1, "prompt_numbers")

    def test_two_negatives_fails_only_negative(self):
        data = self.data()
        data["items"][0]["prompt"] += "禁止兩個負向，避免更多負向。"
        self._assert_only(data, 1, "prompt_negative")

    def test_look_mismatch_fails_only_look(self):
        data = self.data()
        data["items"][2]["look"] = "cinematic"
        self._assert_only(data, 3, "look")

    def test_persuasion_not_allowed_fails_only_persuasion(self):
        data = self.data()
        persuasion = visual.allowed_persuasion("convert", "discount", "none")
        allowed = {"subject_role": ["clear", "hero"], "persuasion": persuasion}
        data["items"][0]["persuasion"] = "testimonial"
        results = validate.check_image_reply(
            data, shape="single", plan=self.plan, allowed=allowed, task_rows=None,
            leak_terms=self.leak_terms, quotable_text=self.quotable_text,
        )
        self._assert_item_only_fails(results, 1, "persuasion")

    def test_subject_role_not_allowed_fails_only_subject_role(self):
        data = self.data()
        allowed = {"subject_role": ["absent", "incidental"], "persuasion": ["none", "countdown"]}
        data["items"][0]["subject_role"] = "hero"
        results = validate.check_image_reply(
            data, shape="single", plan=self.plan, allowed=allowed, task_rows=None,
            leak_terms=self.leak_terms, quotable_text=self.quotable_text,
        )
        self._assert_item_only_fails(results, 1, "subject_role")

    def test_hook_leak_fails_only_leak(self):
        data = self.data()
        data["items"][0]["prompt"] += "「痛點提問」"
        leak_terms = ["痛點提問"]
        results = validate.check_image_reply(
            data, shape="single", plan=self.plan, allowed=self.allowed, task_rows=None,
            leak_terms=leak_terms, quotable_text=self.quotable_text,
        )
        self._assert_item_only_fails(results, 1, "prompt_leak")

    def test_audience_label_leak_fails_only_leak(self):
        data = self.data()
        data["items"][0]["prompt"] += "「陌生・不知有問題」"
        leak_terms = ["陌生・不知有問題"]
        results = validate.check_image_reply(
            data, shape="single", plan=self.plan, allowed=self.allowed, task_rows=None,
            leak_terms=leak_terms, quotable_text=self.quotable_text,
        )
        self._assert_item_only_fails(results, 1, "prompt_leak")

    def test_four_items_same_headline_prefix_fails_round_only(self):
        data = self.data()
        replacements = ["同批頭一句", "同批頭二句", "同批頭三句", "同批頭四句"]
        for i, new_headline in enumerate(replacements):
            old_headline = data["items"][i]["headline"][0]
            data["items"][i]["headline"] = [new_headline]
            data["items"][i]["prompt"] = data["items"][i]["prompt"].replace(
                f"「{old_headline}」", f"「{new_headline}」", 1,
            )
        results = self.check(data)
        repeats = {r["path"]: r for r in results if r["path"].endswith("headline_repeat")}
        self.assertEqual(set(repeats), {"items[3].headline_repeat", "items[4].headline_repeat"})
        self.assertTrue(all(not r["ok"] for r in repeats.values()))
        round_only = ("items_layouts", "items_devices")
        other_bad = [
            r for r in results
            if not r["ok"] and not r["path"].endswith("headline_repeat")
            and r["path"] not in round_only
        ]
        self.assertEqual(other_bad, [])

    def test_all_ten_on_three_devices_fails_round_only(self):
        data = self.data()
        devices = ["contrast", "metaphor", "borrowed_format"]
        for i, item in enumerate(data["items"]):
            item["device"] = devices[i % 3]
        results = self.check(data)
        devices_result = next(r for r in results if r["path"] == "items_devices")
        self.assertFalse(devices_result["ok"])
        per_item_bad = [
            r for r in results
            if not r["ok"] and r["path"] not in ("items_devices", "items_layouts")
            and not r["path"].endswith("headline_repeat")
        ]
        self.assertEqual(per_item_bad, [])

    def test_item_prompt_ratio_missing_in_first_sentence_fails_only_ratio(self):
        data = self.data()
        data["items"][0]["prompt"] = "沒有比例在第一句。" + data["items"][0]["prompt"]
        self._assert_only(data, 1, "prompt_ratio")

    def test_item_prompt_format_bracket_fails_only_format(self):
        data = self.data()
        data["items"][0]["prompt"] += "【誤用方括號】"
        self._assert_only(data, 1, "prompt_format")

    def test_leak_term_outside_quotes_not_flagged(self):
        data = self.data()
        data["items"][0]["prompt"] += "文案外提到痛點提問但沒加引號"
        results = validate.check_image_reply(
            data, shape="single", plan=self.plan, allowed=self.allowed, task_rows=None,
            leak_terms=["痛點提問"], quotable_text=self.quotable_text,
        )
        bad = [r for r in results if not r["ok"]]
        self.assertEqual(bad, [])

    def test_fact_number_outside_quotes_not_flagged(self):
        data = self.data()
        data["items"][0]["prompt"] += "文案外提到999元但沒加引號"
        results = self.check(data)
        bad = [r for r in results if not r["ok"]]
        self.assertEqual(bad, [])

    def test_unknown_layout_not_counted_towards_layouts_seen(self):
        data = self.data()
        known = ["candid_scene", "portrait_focus", "subject_focus", "split_compare"]
        for i, item in enumerate(data["items"]):
            item["layout"] = known[i % 4] if i < 9 else "not_a_real_layout"
        results = self.check(data)
        layouts_result = next(r for r in results if r["path"] == "items_layouts")
        self.assertFalse(layouts_result["ok"], layouts_result)

    def test_opening_repeat_uses_first_headline_element_not_last(self):
        data = self.data()
        for i in (0, 1, 3, 4):
            old_h = data["items"][i]["headline"]
            new_h = [f"獨{i}字串啦", "共用結尾語句"]
            prompt = data["items"][i]["prompt"]
            for old, new in zip(old_h, new_h, strict=True):
                prompt = prompt.replace(f"「{old}」", f"「{new}」", 1)
            data["items"][i]["headline"] = new_h
            data["items"][i]["prompt"] = prompt
        results = self.check(data)
        repeats = [r for r in results if r["path"].endswith("headline_repeat")]
        self.assertEqual(repeats, [])

    def _assert_only(self, data, i, suffix):
        results = self.check(data)
        self._assert_item_only_fails(results, i, suffix)

    def _assert_item_only_fails(self, results, i, suffix):
        subset = _item_paths(results, i)
        bad = [r for r in subset if not r["ok"]]
        self.assertEqual([r["path"] for r in bad], [f"items[{i}].{suffix}"])


# -- fixture v4：六個品牌，系統自己推風格 ---------------------------------------------------

def _v4_leak_terms(coords: list, task_label: str) -> list:
    def value(prefix):
        line = next(c for c in coords if c.startswith(prefix))
        return line.split("：", 1)[1].split("（", 1)[0]

    proof_value = value("證明")
    return visual.leak_terms(
        audience_label=value("受眾"), angle_label=value("切角"), hook_label=value("標題公式"),
        proof_none_label="無證明" if proof_value == "無" else None, task_label=task_label,
    )


class FixtureV4Test(unittest.TestCase):
    def setUp(self):
        self.brands = _load("image_prompt_v4.json")
        self.brands.pop("_note", None)

    def _check(self, key):
        brand = self.brands[key]
        row = visual.task_row(brand["audience_key"], brand["conversion_goal"])
        allowed = _allowed(row["key"], row["subject_roles"], brand["offer_key"], brand["proof_key"])
        leak_terms = _v4_leak_terms(brand["coords"], row["label"])
        fields = ("device", "layout", "look", "subject_role", "persuasion", "headline", "prompt")
        data = {"items": [{k: item[k] for k in fields} for item in brand["items"]]}
        return validate.check_image_reply(
            data, shape="single", plan=brand["plan"], allowed=allowed, task_rows=None,
            leak_terms=leak_terms, quotable_text=brand["quotable_text"],
        )

    def test_every_item_ok_except_coach_item_3(self):
        for key in self.brands:
            with self.subTest(brand=key):
                results = self._check(key)
                for i in (1, 2, 3):
                    subset = _item_paths(results, i)
                    bad = {r["path"]: r["ok"] for r in subset if not r["ok"]}
                    if key == "coach" and i == 3:
                        self.assertEqual(
                            set(bad), {"items[3].headline", "items[3].prompt_quotes"}, bad,
                        )
                    else:
                        self.assertEqual(bad, {})


# -- 輪播：2 concepts × 5 cards -------------------------------------------------------------
# persuasion lives on the concept, not the card (Done 2, ARCHITECTURE.md §5.8 "item fields on
# the concept"); cards carry only {headline, prompt}.

def _card(headline: str) -> dict:
    return {
        "headline": [headline],
        "prompt": f"1:1 輪播卡片，1080×1080。文字卡片示意，主標「{headline}」搭配簡單背景。",
    }


class CarouselTest(unittest.TestCase):
    def setUp(self):
        self.plan = [("brand_spec", "exploit"), ("brand_spec", "exploit")]
        self.allowed = {"subject_role": ["hero", "clear"], "persuasion": ["none"]}

    def _concept(self, layout: str, persuasion: str = "none") -> dict:
        return {
            "device": "contrast", "layout": layout, "look": "brand_spec", "subject_role": "hero",
            "persuasion": persuasion,
            "cards": [_card(f"卡片{i}標題") for i in range(1, 6)],
        }

    def _run(self, data, *, leak_terms=None, quotable_text=""):
        return validate.check_image_reply(
            data, shape="carousel", plan=self.plan, allowed=self.allowed, task_rows=None,
            leak_terms=[] if leak_terms is None else leak_terms, quotable_text=quotable_text,
        )

    def test_two_concepts_five_cards_pass(self):
        data = {"concepts": [self._concept("candid_scene"), self._concept("portrait_focus")]}
        results = self._run(data)
        self.assertEqual([r for r in results if not r["ok"]], [])

    def test_same_layout_both_concepts_fails(self):
        data = {"concepts": [self._concept("candid_scene"), self._concept("candid_scene")]}
        results = self._run(data)
        layout_result = next(r for r in results if r["path"] == "concepts_layout")
        self.assertFalse(layout_result["ok"])

    def test_one_concept_fails(self):
        data = {"concepts": [self._concept("candid_scene")]}
        results = self._run(data)
        bad = {r["path"] for r in results if not r["ok"]}
        self.assertEqual(bad, {"concepts"})

    def test_four_cards_fails(self):
        concept = self._concept("candid_scene")
        concept["cards"] = concept["cards"][:4]
        data = {"concepts": [concept, self._concept("portrait_focus")]}
        results = self._run(data)
        bad = {r["path"] for r in results if not r["ok"]}
        self.assertEqual(bad, {"concepts[1].cards"})

    def test_concept_persuasion_outside_allowed_list_fails(self):
        concept = self._concept("candid_scene", persuasion="offer_headline")
        data = {"concepts": [concept, self._concept("portrait_focus")]}
        results = self._run(data)
        bad = {r["path"] for r in results if not r["ok"]}
        self.assertEqual(bad, {"concepts[1].persuasion"})

    def test_concept_subject_role_outside_allowed_list_fails(self):
        concept = self._concept("candid_scene")
        concept["subject_role"] = "absent"
        data = {"concepts": [concept, self._concept("portrait_focus")]}
        results = self._run(data)
        bad = {r["path"] for r in results if not r["ok"]}
        self.assertEqual(bad, {"concepts[1].subject_role"})

    def test_concept_look_mismatch_fails(self):
        concept = self._concept("candid_scene")
        concept["look"] = "cinematic"
        data = {"concepts": [concept, self._concept("portrait_focus")]}
        results = self._run(data)
        bad = {r["path"] for r in results if not r["ok"]}
        self.assertEqual(bad, {"concepts[1].look"})

    def test_concept_device_outside_list_fails(self):
        concept = self._concept("candid_scene")
        concept["device"] = "not_a_real_device"
        data = {"concepts": [concept, self._concept("portrait_focus")]}
        results = self._run(data)
        bad = {r["path"] for r in results if not r["ok"]}
        self.assertEqual(bad, {"concepts[1].device"})

    def test_concept_layout_outside_list_fails(self):
        concept = self._concept("candid_scene")
        concept["layout"] = "not_a_real_layout"
        data = {"concepts": [concept, self._concept("portrait_focus")]}
        results = self._run(data)
        bad = {r["path"] for r in results if not r["ok"]}
        self.assertEqual(bad, {"concepts[1].layout"})

    def test_trim_image_reply_carousel_limits_to_two_concepts(self):
        data = {"concepts": [{"x": 1}, {"x": 2}, {"x": 3}]}
        validate.trim_image_reply(data, "carousel")
        self.assertEqual(len(data["concepts"]), 2)

    # -- one carousel test per card text rule: a single card breaks only that rule ------------

    def _broken(self, card: dict, **kwargs) -> tuple[dict, dict]:
        concept = self._concept("candid_scene")
        concept["cards"][0] = card
        data = {"concepts": [concept, self._concept("portrait_focus")]}
        return data, kwargs

    def test_card_headline_not_quoted_fails_only_headline(self):
        card = {
            "headline": ["完全不同的字"],
            "prompt": "1:1 輪播卡片，1080×1080。文字卡片示意，主標「卡片1標題」搭配簡單背景。",
        }
        data, _ = self._broken(card)
        bad = {r["path"] for r in self._run(data) if not r["ok"]}
        self.assertEqual(bad, {"concepts[1].cards[1].headline"})

    def test_card_prompt_ratio_missing_in_first_sentence_fails_only_ratio(self):
        card = {
            "headline": ["卡片1標題"],
            "prompt": "沒有比例在第一句。之後才出現 1:1，主標「卡片1標題」搭配簡單背景。",
        }
        data, _ = self._broken(card)
        bad = {r["path"] for r in self._run(data) if not r["ok"]}
        self.assertEqual(bad, {"concepts[1].cards[1].prompt_ratio"})

    def test_card_prompt_format_bracket_fails_only_format(self):
        card = {
            "headline": ["卡片1標題"],
            "prompt": (
                "1:1 輪播卡片，1080×1080。文字卡片示意【誤用方括號】，"
                "主標「卡片1標題」搭配簡單背景。"
            ),
        }
        data, _ = self._broken(card)
        bad = {r["path"] for r in self._run(data) if not r["ok"]}
        self.assertEqual(bad, {"concepts[1].cards[1].prompt_format"})

    def test_card_prompt_quotes_too_long_fails_only_quotes(self):
        long_quote = "測" * 23
        card = {
            "headline": ["卡片1標題"],
            "prompt": (
                "1:1 輪播卡片，1080×1080。文字卡片示意，主標「卡片1標題」，"
                f"小字「{long_quote}」搭配簡單背景。"
            ),
        }
        data, _ = self._broken(card)
        bad = {r["path"] for r in self._run(data) if not r["ok"]}
        self.assertEqual(bad, {"concepts[1].cards[1].prompt_quotes"})

    def test_card_prompt_leak_fails_only_leak(self):
        card = {
            "headline": ["卡片1標題"],
            "prompt": (
                "1:1 輪播卡片，1080×1080。文字卡片示意，主標「卡片1標題」，"
                "小字「痛點提問」搭配簡單背景。"
            ),
        }
        data, kwargs = self._broken(card)
        bad = {r["path"] for r in self._run(data, leak_terms=["痛點提問"]) if not r["ok"]}
        self.assertEqual(bad, {"concepts[1].cards[1].prompt_leak"})

    def test_card_prompt_numbers_fails_only_numbers(self):
        card = {
            "headline": ["卡片1標題"],
            "prompt": (
                "1:1 輪播卡片，1080×1080。文字卡片示意，主標「卡片1標題」，"
                "小字「NT$399」搭配簡單背景。"
            ),
        }
        data, _ = self._broken(card)
        bad = {r["path"] for r in self._run(data) if not r["ok"]}
        self.assertEqual(bad, {"concepts[1].cards[1].prompt_numbers"})

    def test_card_leak_term_outside_quotes_not_flagged(self):
        card = {
            "headline": ["卡片1標題"],
            "prompt": (
                "1:1 輪播卡片，1080×1080。文字卡片示意，主標「卡片1標題」搭配簡單背景。"
                "文案外提到痛點提問但沒加引號。"
            ),
        }
        data, _ = self._broken(card)
        bad = {r["path"] for r in self._run(data, leak_terms=["痛點提問"]) if not r["ok"]}
        self.assertEqual(bad, set())

    def test_card_fact_number_outside_quotes_not_flagged(self):
        card = {
            "headline": ["卡片1標題"],
            "prompt": (
                "1:1 輪播卡片，1080×1080。文字卡片示意，主標「卡片1標題」搭配簡單背景。"
                "文案外提到999元但沒加引號。"
            ),
        }
        data, _ = self._broken(card)
        bad = {r["path"] for r in self._run(data) if not r["ok"]}
        self.assertEqual(bad, set())

    def test_card_prompt_negative_two_fails_only_negative(self):
        card = {
            "headline": ["卡片1標題"],
            "prompt": (
                "1:1 輪播卡片，1080×1080。文字卡片示意，主標「卡片1標題」搭配簡單背景。"
                "禁止兩個負向，避免更多負向。"
            ),
        }
        data, _ = self._broken(card)
        bad = {r["path"] for r in self._run(data) if not r["ok"]}
        self.assertEqual(bad, {"concepts[1].cards[1].prompt_negative"})


# -- 沒有受眾：allowed=None，走 all_task_rows ------------------------------------------------

class NoAudienceTest(unittest.TestCase):
    def setUp(self):
        self.data = copy.deepcopy(_load("image_prompt_v2_A.json"))
        self.plan = [("brand_spec", "exploit")] * 10
        self.task_rows = visual.all_task_rows(None, None, None)

    def test_missing_image_task_fails(self):
        results = validate.check_image_reply(
            self.data, shape="single", plan=self.plan, allowed=None, task_rows=self.task_rows,
            leak_terms=[], quotable_text="（無）",
        )
        expected = [{"path": "image_task", "ok": False, "message": "缺欄位或不在任務表：None"}]
        self.assertEqual(results, expected)

    def test_present_image_task_checks_items_against_that_row(self):
        data = copy.deepcopy(self.data)
        data["image_task"] = "stop_relate"
        results = validate.check_image_reply(
            data, shape="single", plan=self.plan, allowed=None, task_rows=self.task_rows,
            leak_terms=[], quotable_text="（無）\n每顆 150mg 咖啡因",
        )
        image_task_result = next(r for r in results if r["path"] == "image_task")
        self.assertTrue(image_task_result["ok"])
        bad = [r for r in results if not r["ok"]]
        self.assertEqual(bad, [])

    def test_unknown_image_task_key_fails_only_image_task(self):
        results = validate.check_image_reply(
            self.data | {"image_task": "k_x"}, shape="single", plan=self.plan, allowed=None,
            task_rows=self.task_rows, leak_terms=[], quotable_text="（無）",
        )
        expected = [{"path": "image_task", "ok": False, "message": "缺欄位或不在任務表：'k_x'"}]
        self.assertEqual(results, expected)

    def test_stop_relate_row_never_widened_by_offer(self):
        # Decision 2: offer/proof are the set's own coordinates and never widen a row an unknown
        # audience is derived from — stop_relate stays ["none"] regardless of offer_key.
        data = copy.deepcopy(self.data)
        data["image_task"] = "stop_relate"
        data["items"][1]["persuasion"] = "offer_headline"
        task_rows = visual.all_task_rows(None, "discount", None)
        results = validate.check_image_reply(
            data, shape="single", plan=self.plan, allowed=None, task_rows=task_rows,
            leak_terms=[], quotable_text="（無）\n每顆 150mg 咖啡因",
        )
        bad = [r["path"] for r in results if not r["ok"]]
        self.assertEqual(bad, ["items[2].persuasion"])

    _B_QUOTABLE = "滿799免運／限時9折到8/31／累計滿$3000送T-shirt\n每顆含有150mg咖啡因"

    def test_convert_row_countdown_needs_limited_time(self):
        data = copy.deepcopy(_load("image_prompt_v2_B.json"))
        data["image_task"] = "convert"
        task_rows = visual.all_task_rows(None, "discount", None)
        results = validate.check_image_reply(
            data, shape="single", plan=self.plan, allowed=None, task_rows=task_rows,
            leak_terms=[], quotable_text=self._B_QUOTABLE,
        )
        bad = [r["path"] for r in results if not r["ok"]]
        self.assertEqual(bad, ["items[1].persuasion", "items[4].persuasion", "items[8].persuasion"])

    def test_convert_row_testimonial_needs_proof(self):
        data = copy.deepcopy(_load("image_prompt_v2_B.json"))
        data["image_task"] = "convert"
        data["items"][1]["persuasion"] = "testimonial"
        task_rows = visual.all_task_rows(None, "discount", None)
        results = validate.check_image_reply(
            data, shape="single", plan=self.plan, allowed=None, task_rows=task_rows,
            leak_terms=[], quotable_text=self._B_QUOTABLE,
        )
        bad = [r["path"] for r in results if not r["ok"]]
        self.assertEqual(
            bad,
            [
                "items[1].persuasion", "items[2].persuasion", "items[4].persuasion",
                "items[8].persuasion",
            ],
        )


# -- 日常字不誤判；「要不要」不算負向；「請勿」只算一次 --------------------------------------

class EverydayWordsTest(unittest.TestCase):
    def test_everyday_words_never_flagged(self):
        leak_terms = visual.leak_terms(
            audience_label="已購・回購", task_label="讓用過的人再下單一次",
        )
        prompt = (
            "1:1 輪播卡片，1080×1080。主標「太貴也值得」，副標「回購的人都說」，"
            "小字「陌生人也推」與「滿799免運」。"
        )
        quotes = validate._QUOTE_RE.findall(prompt)
        result = validate._check_leak("x", quotes, leak_terms, quotable_text="")
        self.assertTrue(result["ok"], result)

    def test_jargon_term_in_quotable_text_is_exempt(self):
        leak_terms = ["讓人相信有解法"]
        prompt = "1:1。主標「讓人相信有解法」。"
        quotes = validate._QUOTE_RE.findall(prompt)
        result = validate._check_leak("x", quotes, leak_terms, quotable_text="讓人相信有解法")
        self.assertTrue(result["ok"], result)

    def test_yao_bu_yao_is_not_negative(self):
        self.assertEqual(len(visual.NEGATIVE_PATTERN.findall("要不要")), 0)

    def test_qing_wu_counts_once(self):
        self.assertEqual(len(visual.NEGATIVE_PATTERN.findall("請勿")), 1)

    def test_negative_pattern_each_alternative_counts_once(self):
        for word in ["不要", "請勿", "避免", "禁止", "不得", "不出現", "不放", "勿"]:
            with self.subTest(word=word):
                self.assertEqual(len(visual.NEGATIVE_PATTERN.findall(word)), 1)


# -- 表：allowed_persuasion／task_row／shape_for／leak_terms -------------------------------

class TablesTest(unittest.TestCase):
    def test_allowed_persuasion_stop_relate_is_none_only(self):
        self.assertEqual(
            visual.allowed_persuasion("stop_relate", "discount", "customer_review"), ["none"],
        )

    def test_allowed_persuasion_union_in_persuasions_order(self):
        self.assertEqual(
            visual.allowed_persuasion("convert", "limited_time", "customer_review"),
            ["none", "offer_headline", "countdown", "testimonial", "before_after"],
        )

    def test_allowed_persuasion_unknown_keys_contribute_nothing(self):
        self.assertEqual(visual.allowed_persuasion("convert", "k_x", "k_x"), ["none"])

    def test_task_row_label_close_word(self):
        self.assertIn("預約", visual.task_row("warm_engaged", "booking")["label"])
        self.assertIn("下單", visual.task_row("warm_engaged", None)["label"])
        self.assertIn("進一步了解", visual.task_row("warm_engaged", "awareness")["label"])

    def test_all_task_rows_no_offer_or_proof_is_none_only(self):
        rows = visual.all_task_rows(None, None, None)
        self.assertTrue(all(row["persuasion"] == ["none"] for row in rows.values()))

    def test_all_task_rows_order_and_derivation(self):
        rows = visual.all_task_rows("booking", "discount", "sales_numbers")
        self.assertEqual(
            list(rows), ["stop_relate", "believe_solution", "convert", "come_again", "win_back"],
        )
        self.assertEqual(rows["stop_relate"]["persuasion"], ["none"])
        self.assertEqual(
            rows["convert"]["persuasion"],
            ["none", "offer_headline", "price_breakdown", "data_proof"],
        )
        self.assertIn("預約", rows["convert"]["label"])

    def test_shape_for(self):
        self.assertEqual(visual.shape_for("flexible"), "single")
        self.assertEqual(visual.shape_for("single_image"), "single")
        self.assertEqual(visual.shape_for("video"), "single")
        self.assertEqual(visual.shape_for(None), "single")
        self.assertEqual(visual.shape_for("carousel"), "carousel")

    def test_leak_terms_keeps_audience_label_whole(self):
        self.assertEqual(visual.leak_terms(audience_label="互動過・沒買"), ["互動過・沒買"])

    def test_leak_terms_proof_none_only_when_passed(self):
        self.assertEqual(visual.leak_terms(proof_none_label="無證明"), ["無證明"])
        self.assertEqual(visual.leak_terms(), [])

    def test_leak_terms_dedupes_same_label(self):
        self.assertEqual(visual.leak_terms(audience_label="x", angle_label="x"), ["x"])

    def test_shape_for_brand_made_key_is_single(self):
        self.assertEqual(visual.shape_for("k_x"), "single")

    def test_ratio_literal(self):
        self.assertEqual(visual.RATIO, {
            "single": ("4:5", "4:5 直式單圖廣告，1080×1350"),
            "carousel": ("1:1", "1:1 輪播卡片，1080×1080"),
        })

    def test_vocabulary_labels_literal(self):
        self.assertEqual(list(visual.DEVICES.items()), [
            ("contrast", "對照"), ("metaphor", "誇張比喻"), ("borrowed_format", "借用格式"),
            ("frozen_moment", "定格瞬間"), ("demonstration", "直接示範"), ("testimony", "人物證言"),
            ("data_visual", "數據具象"),
        ])
        self.assertEqual(list(visual.LAYOUTS.items()), [
            ("candid_scene", "情境畫面"), ("portrait_focus", "人物特寫"),
            ("subject_focus", "主角特寫"), ("split_compare", "分割對照"),
            ("flat_lay", "俯拍陳列"), ("magazine_cover", "雜誌封面"),
            ("newspaper_editorial", "報紙編輯"), ("zine_collage", "拼貼"),
            ("infographic", "資訊圖表"), ("social_screenshot", "社群截圖"),
            ("screen_mockup", "畫面示意"), ("type_poster", "大字海報"),
        ])
        self.assertEqual(list(visual.SUBJECT_ROLES.items()), [
            ("absent", "不出現"), ("incidental", "順手帶到"), ("clear", "清楚出現"),
            ("hero", "主角"),
        ])
        self.assertEqual(list(visual.PERSUASIONS.items()), [
            ("none", "無"), ("offer_headline", "優惠大字"), ("price_breakdown", "價格拆解"),
            ("countdown", "倒數"), ("testimonial", "顧客證言"), ("credential", "資格背書"),
            ("data_proof", "數據證明"), ("before_after", "前後對比"),
        ])
        self.assertEqual(list(visual.SLOTS.items()), [("exploit", "主力"), ("explore", "探索")])
        self.assertEqual(list(visual.CLOSE_WORDS.items()), [
            ("purchase", "下單"), ("booking", "預約"), ("lead", "留下資料或報名"),
            ("awareness", "進一步了解"),
        ])

    def test_tasks_table_literal(self):
        self.assertEqual(visual.TASKS, {
            "cold_unaware": {
                "key": "stop_relate", "label": "讓人停下來、有共鳴",
                "how": "情境反差、比喻、生活觀察，不推銷",
                "subject_roles": ["absent", "incidental"],
            },
            "cold_problem_aware": {
                "key": "believe_solution", "label": "讓人相信有解法",
                "how": "使用情境、前後對照、把效果或服務現場畫出來（不畫效果數字）",
                "subject_roles": ["clear", "hero"],
            },
            "warm_engaged": {
                "key": "convert", "label": "讓猶豫的人{close}",
                "how": "主角主視覺、誘因與截止、打消疑慮",
                "subject_roles": ["clear", "hero"],
            },
            "customer_repeat": {
                "key": "come_again", "label": "讓用過的人再{close}一次",
                "how": "補齊、時間感、成套",
                "subject_roles": ["clear", "hero"],
            },
            "lapsed": {
                "key": "win_back", "label": "讓很久沒回來的人想起來",
                "how": "給回來的理由、有什麼不一樣了",
                "subject_roles": ["clear"],
            },
        })

    def test_offer_and_proof_persuasion_tables_literal(self):
        self.assertEqual(visual.OFFER_PERSUASION, {
            "discount": ["offer_headline", "price_breakdown"],
            "limited_time": ["offer_headline", "countdown"],
            "bundle": ["offer_headline"],
            "trial_sample": ["offer_headline"],
            "guarantee": ["offer_headline"],
            "free_shipping": ["offer_headline"],
            "none": [],
        })
        self.assertEqual(visual.PROOF_PERSUASION, {
            "customer_review": ["testimonial", "before_after"],
            "founder_voice": ["testimonial"],
            "expert_endorsement": ["credential"],
            "lab_report": ["credential"],
            "media_coverage": ["credential"],
            "sales_numbers": ["data_proof"],
            "none": [],
        })

    def test_all_task_rows_subject_role_matches_row(self):
        rows = visual.all_task_rows(None, None, None)
        self.assertEqual(rows["stop_relate"]["subject_role"], ["absent", "incidental"])
        self.assertEqual(rows["convert"]["subject_role"], ["clear", "hero"])
        self.assertEqual(rows["win_back"]["subject_role"], ["clear"])

    def test_task_row_how_and_subject_roles_are_source_literal(self):
        row = visual.task_row("lapsed", None)
        self.assertEqual(row["how"], "給回來的理由、有什麼不一樣了")
        self.assertEqual(row["subject_roles"], ["clear"])

    def test_all_task_rows_how_is_source_literal(self):
        rows = visual.all_task_rows(None, None, None)
        self.assertEqual(rows["win_back"]["how"], "給回來的理由、有什麼不一樣了")

    def test_leak_terms_hook_label_included(self):
        self.assertEqual(visual.leak_terms(hook_label="標題公式X"), ["標題公式X"])


# -- spec_warnings：品牌事實裡的負向句 -------------------------------------------------------

class SpecWarningsTest(unittest.TestCase):
    def test_probe_spec_has_no_warning(self):
        spec_text = (FIXTURES / "spec.txt").read_text(encoding="utf-8")
        self.assertEqual(visual.spec_warnings("b1", spec_text), [])

    def test_three_negatives_gives_one_warning_with_href(self):
        warnings = visual.spec_warnings("b1", "不要A，禁止B，避免C")
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["href"], "/brands/b1/library?tab=facts")
        self.assertIn("3", warnings[0]["text"])

    def test_none_spec_is_no_warning(self):
        self.assertEqual(visual.spec_warnings("b1", None), [])

    def test_exactly_two_negatives_is_no_warning(self):
        self.assertEqual(visual.spec_warnings("b1", "不要A，禁止B"), [])


# -- 直接測 validate.py 的邊界輔助函式 ------------------------------------------------------

class ValidateHelperBoundaryTest(unittest.TestCase):
    def test_check_headline_exact_max_length_passes_one_over_fails(self):
        h14 = "測" * 14
        h15 = "測" * 15
        r14 = validate._check_headline("p", [h14], [h14])
        self.assertTrue(r14["ok"], r14)
        r15 = validate._check_headline("p", [h15], [h15])
        self.assertFalse(r15["ok"], r15)

    def test_check_headline_shape_boundaries(self):
        self.assertFalse(validate._check_headline("p", [], ["a"])["ok"])
        three = ["a", "b", "c"]
        self.assertFalse(validate._check_headline("p", three, three)["ok"])

    def test_check_prompt_ratio_only_checks_first_sentence(self):
        prompt = "這是第一句沒有比例。後面才出現 4:5 字樣。"
        result = validate._check_prompt_ratio("p", prompt, "4:5")
        self.assertFalse(result["ok"], result)

    def test_check_prompt_format_catches_bracket_alone(self):
        result = validate._check_prompt_format("p", "普通文字【被誤用的方括號】更多字")
        self.assertFalse(result["ok"], result)

    def test_check_prompt_format_catches_code_pattern_alone(self):
        result = validate._check_prompt_format("p", "普通文字 layout_candid 更多字，沒有方括號")
        self.assertFalse(result["ok"], result)

    def test_check_prompt_format_lookbehind_spares_word_boundary_case(self):
        # the code-pattern regex's lookbehind: a run preceded by a letter (iPhone_case's
        # "hone_case") never counts as a code fragment.
        result = validate._check_prompt_format("p", "普通文字 iPhone_case 更多字，沒有方括號")
        self.assertTrue(result["ok"], result)

    def test_fact_numbers_keep_comma_in_prefix_form(self):
        self.assertEqual(validate._fact_numbers("「滿1,000」"), ["1,000"])

    def test_fact_numbers_keep_comma_in_unit_suffix_form(self):
        self.assertEqual(validate._fact_numbers("「1,280元」"), ["1,280"])

    def test_check_quotes_exact_max_length_passes_one_over_fails(self):
        q22 = "測" * 22
        q23 = "測" * 23
        self.assertTrue(validate._check_quotes("p", [q22])["ok"])
        self.assertFalse(validate._check_quotes("p", [q23])["ok"])

    def test_check_quotes_count_over_max_fails(self):
        quotes = [f"字{i}" for i in range(7)]
        result = validate._check_quotes("p", quotes)
        self.assertFalse(result["ok"], result)

    def test_fact_number_prefixes_and_units(self):
        for prefix in ("$", "NT$", "滿", "剩", "第"):
            with self.subTest(prefix=prefix):
                self.assertEqual(validate._fact_numbers(f"「{prefix}88」"), ["88"])
        units = (
            "元", "折", "%", "％", "mg", "g", "ml", "盒", "包", "入", "組", "件", "顆", "堂",
            "次", "位", "人", "天", "小時", "分鐘",
        )
        for unit in units:
            with self.subTest(unit=unit):
                self.assertEqual(validate._fact_numbers(f"「88{unit}」"), ["88"])

    def test_plain_clock_and_date_are_not_fact_numbers(self):
        self.assertEqual(validate._fact_numbers("「10:30」"), [])
        self.assertEqual(validate._fact_numbers("「9/15」"), [])
        self.assertEqual(validate._fact_numbers("「00:07:31」"), ["00:07:31"])
