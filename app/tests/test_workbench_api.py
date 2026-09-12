"""app/tests/test_workbench_api.py — `/api/workbench/*` over HTTP.

F02-I03 (ARCHITECTURE.md §5.1-§5.5, `.work/features/F02.md` "API surface"): the brief-shaped
endpoints this file used to cover (`/briefs`, run-a-part, adopt, close/reopen, delete) are
retired with the page that was their only consumer — see git history for the old six-case
suite. Their replacements (pack/set list/detail, run-a-product, select/deselect, completion,
approve, close) are covered by `test_workbench_pack_api.py` and `test_workbench_approve.py`.
This file keeps only what is unaffected by the reset: `GET /styles`, the one endpoint that
does not belong to a brand and stays exactly as it was.
"""

import unittest

from fastapi.testclient import TestClient

import app.main as main


class StylesTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_list_styles(self):
        resp = self.client.get("/api/workbench/styles")
        self.assertEqual(resp.status_code, 200)
        styles = resp.json()["styles"]
        self.assertTrue(styles)
        self.assertIn("key", styles[0])
        self.assertIn("label", styles[0])


if __name__ == "__main__":
    unittest.main()
