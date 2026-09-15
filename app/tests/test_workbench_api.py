"""app/tests/test_workbench_api.py — `/api/workbench/*` over HTTP.

F02-I03 (ARCHITECTURE.md §5.1-§5.5, `.work/features/F02.md` "API surface"): the brief-shaped
endpoints this file used to cover (`/briefs`, run-a-part, adopt, close/reopen, delete) are
retired with the page that was their only consumer — see git history for the old six-case
suite. Their replacements (pack/set list/detail, run-a-product, select/deselect, completion,
approve, close) are covered by `test_workbench_pack_api.py` and `test_workbench_approve.py`.

F07-I09 (ARCHITECTURE.md §5.10, F07 Decision 25): `GET /styles` — the last endpoint this file
covered — retires with the global style library. This file now only guards that the route stays
gone (Y01: registering it again in memory must turn this red).
"""

import unittest

from fastapi.testclient import TestClient

import app.main as main


class StylesRouteRetiredTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_styles_route_is_gone(self):
        resp = self.client.get("/api/workbench/styles")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
