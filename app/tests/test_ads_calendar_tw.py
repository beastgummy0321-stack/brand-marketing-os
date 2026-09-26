"""app/tests/test_ads_calendar_tw.py — F33-I02 falsifiers for the static Taiwan calendar
(Contract Q): a period over 2026-09-26…10-16 yields 中秋節及教師節 and 國慶日 but not the
開學週 before it nor 雙 11 after it; a 2028 period yields the coverage note instead of a silent
empty list; every table row has valid ISO dates with start <= end and a known kind; the prompt
section prints the header, one line per row, and the explicit empty line when nothing overlaps.
"""

import unittest
from datetime import date

from app.ads import calendar_tw


class EventsBetweenTest(unittest.TestCase):
    def test_period_over_national_day_2026_lists_the_overlapping_rows_only(self):
        rows = calendar_tw.events_between(date(2026, 9, 26), date(2026, 10, 16))
        names = [row["name"] for row in rows]
        self.assertIn("中秋節及教師節", names)
        self.assertIn("國慶日", names)
        self.assertNotIn("開學週", names)
        self.assertNotIn("雙 11 檔", names)
        self.assertNotIn("中秋送禮檔", names)  # ends 09-24, before the period
        self.assertEqual([row["start"] for row in rows], sorted(row["start"] for row in rows))
        for row in rows:
            self.assertEqual(set(row), {"start", "end", "name", "kind", "note"})
            self.assertNotIn("source", row)

    def test_single_day_range_on_a_holiday_finds_it(self):
        rows = calendar_tw.events_between(date(2026, 10, 9), date(2026, 10, 9))
        self.assertEqual([row["name"] for row in rows], ["國慶日"])

    def test_year_outside_the_table_yields_no_rows_and_a_coverage_note(self):
        self.assertEqual(calendar_tw.events_between(date(2028, 1, 1), date(2028, 1, 31)), [])
        note = calendar_tw.coverage_note(date(2028, 1, 1), date(2028, 1, 31))
        self.assertIsNotNone(note)
        assert note is not None
        self.assertIn("2028", note)
        self.assertIn("沒有資料", note)
        self.assertIn("不要假設沒有活動", note)

    def test_range_crossing_out_of_the_table_names_only_the_missing_years(self):
        note = calendar_tw.coverage_note(date(2027, 12, 20), date(2028, 1, 5))
        assert note is not None
        self.assertIn("2028", note)
        self.assertNotIn("2027 年的", note)

    def test_covered_years_have_no_coverage_note(self):
        self.assertIsNone(calendar_tw.coverage_note(date(2026, 1, 1), date(2027, 12, 31)))


class TableIntegrityTest(unittest.TestCase):
    def test_every_row_has_valid_iso_dates_in_order_and_a_known_kind(self):
        self.assertTrue(calendar_tw.EVENTS)
        for row in calendar_tw.EVENTS:
            start = date.fromisoformat(row["start"])
            end = date.fromisoformat(row["end"])
            self.assertLessEqual(start, end, row)
            self.assertIn(row["kind"], calendar_tw.KINDS, row)
            self.assertIn(start.year, calendar_tw.COVERED_YEARS, row)
            self.assertIn(end.year, calendar_tw.COVERED_YEARS, row)
            self.assertTrue(row["source"], row)
            self.assertTrue(row["name"], row)

    def test_conventions_carry_the_shared_note_and_official_rows_cite_a_source(self):
        for row in calendar_tw.EVENTS:
            if row["source"] == "convention":
                self.assertEqual(row["note"], "概略檔期，各校／各平台不同", row)
            else:
                self.assertIn(".", row["source"], row)


class PromptSectionTest(unittest.TestCase):
    def test_section_lists_rows_with_kind_labels(self):
        text = calendar_tw.prompt_section(date(2026, 10, 1), date(2026, 10, 10))
        self.assertTrue(text.startswith("【投放期間內的行事曆】\n"))
        self.assertIn("- 10/09～10/11 國慶日（假日）", text)
        self.assertNotIn("期間內沒有登記的假日、考季或檔期", text)
        self.assertNotIn("不要假設沒有活動", text)

    def test_empty_period_says_so_explicitly(self):
        text = calendar_tw.prompt_section(date(2026, 7, 20), date(2026, 7, 25))
        self.assertEqual(text, "【投放期間內的行事曆】\n期間內沒有登記的假日、考季或檔期")

    def test_uncovered_year_appends_the_coverage_note(self):
        text = calendar_tw.prompt_section(date(2028, 3, 1), date(2028, 3, 10))
        self.assertIn("期間內沒有登記的假日、考季或檔期\n", text)
        self.assertIn("2028 年的假日與考季沒有資料", text)

    def test_missing_dates_do_not_pretend_the_period_is_quiet(self):
        text = calendar_tw.prompt_section(None, date(2026, 3, 10))
        self.assertIn("期間還沒設定", text)
        self.assertNotIn("期間內沒有登記", text)


if __name__ == "__main__":
    unittest.main()
