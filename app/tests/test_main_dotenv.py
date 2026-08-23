# -*- coding: utf-8 -*-
"""app/tests/test_main_dotenv.py — `.env` 自己讀（2026-08-23）。

原本只有「啟動行銷系統.bat」把 `.env` 灌進環境變數，換個方式啟動就悄悄沒有金鑰，
Meta 顯示「還沒連接」而 AI 因為有資料庫備援不會露餡。解析是純函數，這裡直接測它；
另外鎖住「測試中不得讀真的 .env」這條安全線。
"""

import unittest

import app.main as main


class ParseEnvFileTest(unittest.TestCase):

    def test_basic_key_value(self):
        self.assertEqual(main._parse_env_file("A=1\nB=2"), {"A": "1", "B": "2"})

    def test_value_containing_equals_is_not_split_again(self):
        """base64／JWT 金鑰裡會有等號，只能切第一個。"""
        self.assertEqual(main._parse_env_file("TOKEN=abc=def==")["TOKEN"], "abc=def==")

    def test_comments_and_blank_lines_ignored(self):
        text = "# 這是註解\n\n   \nA=1\n#B=2"
        self.assertEqual(main._parse_env_file(text), {"A": "1"})

    def test_line_without_equals_ignored(self):
        self.assertEqual(main._parse_env_file("JUST_A_WORD\nA=1"), {"A": "1"})

    def test_whitespace_trimmed(self):
        self.assertEqual(main._parse_env_file("  A  =  1  "), {"A": "1"})

    def test_matching_quotes_stripped(self):
        parsed = main._parse_env_file("A=\"1\"\nB='2'\nC=\"3\nD='mixed\"")
        self.assertEqual(parsed["A"], "1")
        self.assertEqual(parsed["B"], "2")
        self.assertEqual(parsed["C"], '"3', "單邊引號不是成對，不能亂剝")
        self.assertEqual(parsed["D"], "'mixed\"", "頭尾不同種引號，不能剝")

    def test_empty_value_kept(self):
        self.assertEqual(main._parse_env_file("A="), {"A": ""})


class LoadDotenvSafetyTest(unittest.TestCase):
    """安全線：測試程序絕對不能吃到真的金鑰，誤打出去要花錢。"""

    def test_load_dotenv_is_a_noop_under_pytest(self):
        self.assertEqual(main._load_dotenv(), 0)


if __name__ == "__main__":
    unittest.main()
