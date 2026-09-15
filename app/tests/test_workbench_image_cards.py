"""app/tests/test_workbench_image_cards.py — F07-I08 (ARCHITECTURE.md §5.7 (② count), §5.11;
Decisions 26-27): pure tests for `app/workbench/image_cards.py`, bodies built in the §5.8
shape (`{title, headline, prompt, text, fingerprint, cards, round, ...}`).

Fixture shape (`.harness/scratch/mutants/F07-I08/rules.md` "Fixture requirements"): the
prompt carries three distinct 「」 strings out of alphabetical/prompt-order (`Zulu`, `Alpha`,
`Echo`), one of them (`Zulu`) repeated, and one (`Zulu`/`Echo`) not equal to `headline`
(`Alpha`); the tail (brand identity text) carries its own unrelated 「」 string (`Foxtrot`) so
a mutant scanning `body.text` instead of `body.prompt` is caught. Rule IDs below reference
that file.
"""

import unittest

from app.workbench import image_cards

_PROMPT = (
    "這是這一張的畫面描述，「Zulu」擺在最上方，「Alpha」放在中段，"
    "「Zulu」重複出現一次，最後放「Echo」。"
)
_TAIL = "品牌視覺規範：識別文字「Foxtrot」\n風格規範：柔光生活"
_VARIANT_CHANGES = [
    "背景色調", "取景遠近", "文字位置", "強調色", "姿勢或表情", "光線時段", "景深",
    "背景色調＋強調色", "取景遠近＋文字位置",
]


def _expected_variant_text(count: int) -> str:
    lines = [
        f"以附上的這張圖為基底，另外生成 {count} 張變體，一張一張出，主體不變、其他部分些許改變。",
        "保持不變：畫面主體與人物、參考照的外型、4:5 直式單圖廣告，1080×1350、文字的層級，"
        "以及圖上每一段字逐字不改：「Zulu」「Alpha」「Echo」。",
        "每張只改一到兩個地方：",
        *[f"{i} {_VARIANT_CHANGES[i - 1]}" for i in range(1, count + 1)],
        _TAIL,
    ]
    return "\n".join(lines)


def _fingerprint(*, look="phone_raw", look_label="手機原生抓拍", layout="candid_scene",
                  layout_label="情境畫面", device="contrast", device_label="對照",
                  persuasion="none", persuasion_label="無", slot="exploit", slot_label="主力"):
    return {
        "image_task": {"key": "convert", "label": "讓猶豫的人下單"},
        "device": {"key": device, "label": device_label},
        "layout": {"key": layout, "label": layout_label},
        "look": {"key": look, "label": look_label},
        "subject_role": {"key": "hero", "label": "主角"},
        "persuasion": {"key": persuasion, "label": persuasion_label},
        "slot": {"key": slot, "label": slot_label},
    }


def _round(*, format_key="single_image", recommended_index=1):
    return {
        "format": format_key, "audience_key": "warm_engaged", "image_task": "convert",
        "identity_id": "wvi_1", "identity_text": "品牌識別文字",
        "plan": [{"look": "phone_raw", "slot": "exploit"}],
        "look_order": {"exploit": ["phone_raw"], "explore": []},
        "recommended_index": recommended_index, "recommended_slot": "exploit",
        "learning_ids": [],
    }


def _body(**overrides):
    body = {
        "title": "情境對照", "headline": "Alpha",
        "prompt": _PROMPT, "text": f"{_PROMPT}\n\n{_TAIL}",
        "fingerprint": _fingerprint(), "cards": None, "round": _round(),
        "validation": [], "warnings": [],
    }
    body.update(overrides)
    return body


class VariantTextTest(unittest.TestCase):
    """V01-V14: the whole ② 變體 text, byte for byte."""

    def test_count_3_exact_text(self):
        self.assertEqual(image_cards.variant_text(_body(), 3), _expected_variant_text(3))

    def test_count_9_exact_text(self):
        self.assertEqual(image_cards.variant_text(_body(), 9), _expected_variant_text(9))


class PromptCardsTest(unittest.TestCase):
    def test_unselected_single_is_one_card(self):
        # C04
        body = _body()
        cards = image_cards.prompt_cards(
            body, version_index=1, selected=False, variant_count=3,
        )
        self.assertEqual(cards, [{"label": "01｜情境對照", "text": body["text"]}])

    def test_label_padding_and_title_not_headline(self):
        # C02: version_index 7 -> "07｜<title>", and title (情境對照) != headline (Alpha) —
        # a mutant reading headline[0] instead of title would fail this.
        body = _body()
        cards = image_cards.prompt_cards(
            body, version_index=7, selected=False, variant_count=0,
        )
        self.assertEqual(cards[0]["label"], "07｜情境對照")

    def test_card_text_is_full_text_not_prompt(self):
        # C03
        body = _body()
        cards = image_cards.prompt_cards(
            body, version_index=1, selected=False, variant_count=0,
        )
        self.assertEqual(cards[0]["text"], body["text"])
        self.assertTrue(cards[0]["text"].endswith("風格規範：柔光生活"))

    def test_selected_single_variant_count_3(self):
        # C01 (has text -> not []), C08 (exact ② label)
        body = _body()
        cards = image_cards.prompt_cards(
            body, version_index=1, selected=True, variant_count=3,
        )
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[1], {"label": "② 變體", "text": image_cards.variant_text(body, 3)})

    def test_variant_count_0_has_no_variant_card(self):
        # C07
        body = _body()
        cards = image_cards.prompt_cards(
            body, version_index=1, selected=True, variant_count=0,
        )
        self.assertEqual(len(cards), 1)

    def test_selected_carousel_has_no_variant_card(self):
        # C05
        body = _body(round=_round(format_key="carousel"))
        cards = image_cards.prompt_cards(
            body, version_index=1, selected=True, variant_count=5,
        )
        self.assertEqual(len(cards), 1)

    def test_flexible_and_none_format_are_single_shape(self):
        # C06
        for format_key in ("flexible", None):
            body = _body(round=_round(format_key=format_key))
            cards = image_cards.prompt_cards(
                body, version_index=1, selected=True, variant_count=3,
            )
            self.assertEqual(len(cards), 2, format_key)
            self.assertEqual(cards[1]["label"], "② 變體")

    def test_pre_f07_body_is_empty(self):
        # C01
        body = {"mode": "variant", "rendered": {"hero": "x", "variant": "y"}}
        self.assertEqual(
            image_cards.prompt_cards(body, version_index=1, selected=True, variant_count=3),
            [],
        )


class BadgesTest(unittest.TestCase):
    def test_recommended_explore_item(self):
        # B01, B02, B03 (order: slot label first, then 建議選這張)
        body = _body(
            fingerprint=_fingerprint(slot="explore", slot_label="探索"),
            round=_round(recommended_index=1),
        )
        self.assertEqual(image_cards.badges(body, 1), ["探索", "建議選這張"])

    def test_explore_not_recommended(self):
        # B01: an explore, non-recommended body must read ["探索"], not ["主力"].
        body = _body(
            fingerprint=_fingerprint(slot="explore", slot_label="探索"),
            round=_round(recommended_index=2),
        )
        self.assertEqual(image_cards.badges(body, 1), ["探索"])

    def test_exploit_not_recommended(self):
        # B01: an exploit, non-recommended body must read ["主力"], not ["探索"].
        body = _body(round=_round(recommended_index=2))
        self.assertEqual(image_cards.badges(body, 1), ["主力"])

    def test_pre_f07_body_is_empty(self):
        # B04
        self.assertEqual(image_cards.badges({}, 1), [])
        self.assertEqual(image_cards.badges(None, 1), [])


class FingerprintTextTest(unittest.TestCase):
    def test_omits_none_persuasion(self):
        # F01, F02
        body = _body()
        self.assertEqual(image_cards.fingerprint_text(body), "手機原生抓拍 · 情境畫面 · 對照")

    def test_includes_non_none_persuasion(self):
        # F02
        body = _body(
            fingerprint=_fingerprint(persuasion="offer_headline", persuasion_label="優惠大字"),
        )
        self.assertEqual(
            image_cards.fingerprint_text(body), "手機原生抓拍 · 情境畫面 · 對照 · 優惠大字",
        )

    def test_pre_f07_body_is_none(self):
        # F03
        self.assertIsNone(image_cards.fingerprint_text({}))
        self.assertIsNone(image_cards.fingerprint_text(None))


class CopyAllTextTest(unittest.TestCase):
    def test_ten_single_bodies_in_given_order(self):
        # A01, A03, A05
        def _one(i: int) -> dict:
            prompt = f"第{i}則描述。「主標{i}」"
            return _body(title=f"點子{i}", prompt=prompt, text=f"{prompt}\n\n{_TAIL}")

        bodies = [_one(i) for i in range(1, 11)]
        text = image_cards.copy_all_text(bodies)
        assert text is not None
        self.assertTrue(
            text.startswith("請一次生成 10 張圖，每張只照下面對應的那一段，一段一張，不要合併。"),
        )
        for i in range(1, 11):
            self.assertIn(f"第 {i} 張\n{bodies[i - 1]['text']}", text)

    def test_carousel_two_concepts_ten_cards_in_order(self):
        # A02, A04, A05
        def card(i: int) -> dict:
            return {"headline": f"h{i}", "prompt": f"卡{i}", "text": f"卡{i}\n\n{_TAIL}"}

        bodies = [
            _body(round=_round(format_key="carousel"), cards=[card(i) for i in range(1, 6)]),
            _body(round=_round(format_key="carousel"), cards=[card(i) for i in range(6, 11)]),
        ]
        text = image_cards.copy_all_text(bodies)
        assert text is not None
        expected_lead = (
            "請一次生成 10 張圖：兩組輪播各 5 張，每張只照下面對應的那一段，一段一張，不要合併。"
        )
        self.assertTrue(text.startswith(expected_lead))
        for i in range(1, 11):
            self.assertIn(f"第 {i} 張\n卡{i}\n\n{_TAIL}", text)

    def test_pre_f07_bodies_is_none(self):
        # A06
        bodies = [{"mode": "variant", "rendered": {"hero": "x", "variant": "y"}}]
        self.assertIsNone(image_cards.copy_all_text(bodies))

    def test_flexible_format_reads_as_single(self):
        # A02c: a `flexible`-format round gets the single lead and one 「第 N 張」 block
        # per body, same as `single_image`.
        def _one(i: int) -> dict:
            prompt = f"第{i}則描述。「主標{i}」"
            return _body(
                round=_round(format_key="flexible"), title=f"點子{i}",
                prompt=prompt, text=f"{prompt}\n\n{_TAIL}",
            )

        bodies = [_one(i) for i in range(1, 11)]
        text = image_cards.copy_all_text(bodies)
        assert text is not None
        self.assertTrue(
            text.startswith("請一次生成 10 張圖，每張只照下面對應的那一段，一段一張，不要合併。"),
        )
        for i in range(1, 11):
            self.assertIn(f"第 {i} 張\n{bodies[i - 1]['text']}", text)


if __name__ == "__main__":
    unittest.main()
