"""app/tests/test_workbench_brief_text.py — F39-I04: `prompts.brief_text` prints the ad's scene
and the period's calendar when the brief's `request_json` carries them (F39 outcomes 3–4), and
prints exactly the pre-F39 text when it does not. Pure-function tests on dict briefs, no DB
(`test_workbench.py` §BriefCoordinatesTextTest is the legacy sibling; it pins the unchanged path).
"""

import json
import unittest

from app.workbench import prompts

SCENE = "早上七點趕出門，站在流理台前一口氣喝完"
CALENDAR = "- 10/10～10/10 國慶日（holiday）\n- 10/20～10/31 期中考週（exam）"
SCENE_LINE = (
    f"情境：{SCENE}（五組文案的畫面都發生在這個情境裡，不得換成別的情境；"
    "標題與內文要看得出這個情境）"
)
CALENDAR_BLOCK = (
    "投放期間的行事曆：\n" + CALENDAR
    + "\n（只在它真的會影響買家時寫進標題或 hook，不必硬套節慶）"
)
COORDINATES = {"audience": "上班族", "offer": "限時限量"}


def _brief(**request) -> dict:
    return {
        "coordinates_snapshot_json": dict(COORDINATES),
        "visual_tone": None,
        "visual_concept": None,
        "request_json": {"offer_deadline": "2026-10-31", **request},
    }


# The exact pre-F39 text for a brief with coordinates and a deadline — pins the line order:
# coordinates → (scene) → deadline → (calendar) → visual_tone → visual_concept.
BASELINE = "\n".join([
    "## 這張工單",
    "產品：測試產品",
    "這個節點的座標（文案照這組座標寫）：" + json.dumps(COORDINATES, ensure_ascii=False)
    + "\n例外：優惠與證明分類不是已確認事實；須另有已確認來源，否則使用無優惠／無證明。",
    "限時截止日：2026-10-31（限時限量文案只能寫這一個日期，不得另造期限或數量）",
    "visual_tone：（無）",
    "visual_concept：（無）",
])


class BriefTextSceneTest(unittest.TestCase):
    def test_scene_line_when_handed_over(self):
        text = prompts.brief_text(_brief(scene=SCENE), "測試產品")
        self.assertIn(SCENE_LINE, text)

    def test_no_scene_line_without_scene(self):
        for request in ({}, {"scene": None}, {"scene": ""}, {"scene": "   "}):
            with self.subTest(request=request):
                text = prompts.brief_text(_brief(**request), "測試產品")
                self.assertNotIn("情境：", text)

    def test_scene_sits_between_coordinates_and_deadline(self):
        text = prompts.brief_text(_brief(scene=SCENE), "測試產品")
        self.assertLess(text.index("這個節點的座標"), text.index("情境："))
        self.assertLess(text.index("情境："), text.index("限時截止日"))


class BriefTextCalendarTest(unittest.TestCase):
    def test_calendar_block_when_handed_over(self):
        text = prompts.brief_text(_brief(calendar_note=CALENDAR), "測試產品")
        self.assertIn(CALENDAR_BLOCK, text)

    def test_no_calendar_block_without_note(self):
        for request in ({}, {"calendar_note": None}, {"calendar_note": ""}):
            with self.subTest(request=request):
                text = prompts.brief_text(_brief(**request), "測試產品")
                self.assertNotIn("投放期間的行事曆", text)
                self.assertNotIn("不必硬套節慶", text)

    def test_calendar_sits_between_deadline_and_visual_tone(self):
        text = prompts.brief_text(_brief(calendar_note=CALENDAR), "測試產品")
        self.assertLess(text.index("限時截止日"), text.index("投放期間的行事曆"))
        self.assertLess(text.index("投放期間的行事曆"), text.index("visual_tone："))


CUSTOMER_GROUP = (
    "下班後夜跑的上班族｜煩惱：怕買錯｜顧客會說：晚上跑步車子看不到我｜什麼時候用：下班後在河濱夜跑"
)
CUSTOMER_GROUP_LINE = (
    f"顧客群：{CUSTOMER_GROUP}（五組文案都寫給這一群人，情境是他們的時刻）"
)


class BriefTextCustomerGroupTest(unittest.TestCase):
    """F46-I01 (Contract A): `request_json.customer_group` prints one line right after the
    scene line, only when present."""

    def test_line_follows_the_scene_when_handed_over(self):
        text = prompts.brief_text(_brief(scene=SCENE, customer_group=CUSTOMER_GROUP), "測試產品")
        self.assertIn(SCENE_LINE + "\n" + CUSTOMER_GROUP_LINE + "\n限時截止日：", text)

    def test_line_without_a_scene_still_sits_before_the_deadline(self):
        text = prompts.brief_text(_brief(customer_group=CUSTOMER_GROUP), "測試產品")
        self.assertEqual(
            text, BASELINE.replace("限時截止日：", CUSTOMER_GROUP_LINE + "\n限時截止日：", 1),
        )

    def test_no_line_without_a_group(self):
        for request in ({}, {"customer_group": None}, {"customer_group": ""},
                        {"customer_group": "  "}):
            with self.subTest(request=request):
                text = prompts.brief_text(_brief(**request), "測試產品")
                self.assertNotIn("顧客群：", text)
                self.assertEqual(text, BASELINE)


class BriefTextUnchangedPathTest(unittest.TestCase):
    def test_both_absent_is_the_exact_pre_f39_text(self):
        self.assertEqual(prompts.brief_text(_brief(), "測試產品"), BASELINE)

    def test_both_present_is_baseline_with_the_two_blocks_inserted(self):
        text = prompts.brief_text(_brief(scene=SCENE, calendar_note=CALENDAR), "測試產品")
        expected = BASELINE.replace(
            "限時截止日：", SCENE_LINE + "\n限時截止日：", 1,
        ).replace(
            "\nvisual_tone：", "\n" + CALENDAR_BLOCK + "\nvisual_tone：", 1,
        )
        self.assertEqual(text, expected)

    def test_scene_and_calendar_do_not_need_a_deadline(self):
        """Neither block hangs off the deadline branch: a 無優惠 brief with no deadline still
        prints them, in the same relative order."""
        text = prompts.brief_text({
            "coordinates_snapshot_json": {"offer": "無優惠"},
            "request_json": {"scene": SCENE, "calendar_note": CALENDAR},
        }, "產品")
        self.assertIn(SCENE_LINE, text)
        self.assertIn(CALENDAR_BLOCK, text)
        self.assertNotIn("限時", text)
        self.assertLess(text.index("情境："), text.index("投放期間的行事曆"))


if __name__ == "__main__":
    unittest.main()
