"""One GET per source page, fixed host/path, no token-bearing next URL replay."""

import unittest
from unittest.mock import patch

from app.meta import graph


class ExternalGraphTest(unittest.TestCase):
    def test_page_is_bounded_and_never_follows_next_url(self):
        payload = {
            "data": [{"id": "2"}],
            "paging": {"next": "https://evil/?access_token=secret", "cursors": {"after": "opaque"}},
        }
        with patch.object(graph, "fetch_page", return_value=payload) as fetch:
            result = graph.external_page("secret", "1", "campaigns")
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(result["cursor"], "opaque")
        self.assertNotIn("secret", str(result))
        self.assertEqual(fetch.call_args.args[0], graph.GRAPH_BASE_URL + "/act_1/campaigns")
        self.assertEqual(fetch.call_args.kwargs["params"]["limit"], 100)

    def test_errors_and_cursor_cannot_leak_token(self):
        with patch.object(
            graph, "fetch_page", return_value={"error": {"code": 190, "message": "secret"}}
        ):
            with self.assertRaises(graph.GraphError) as caught:
                graph.external_page("secret", "1", "campaigns")
        self.assertNotIn("secret", str(caught.exception))
        with self.assertRaises(graph.GraphError):
            graph.external_page("secret", "https://evil", "campaigns")
        with patch.object(
            graph, "fetch_page", return_value={"data": [], "paging": {"next": "bad"}}
        ):
            with self.assertRaises(graph.GraphError):
                graph.external_page("secret", "1", "campaigns")

    def test_actual_transport_uses_get_only(self):
        with (
            patch.object(graph.httpx, "get") as get,
            patch.object(graph.httpx, "post", side_effect=AssertionError("write")),
            patch.object(graph.httpx, "patch", side_effect=AssertionError("write")),
            patch.object(graph.httpx, "delete", side_effect=AssertionError("write")),
        ):
            get.return_value.json.return_value = {"data": []}
            graph.external_page("secret", "1", "campaigns")
            self.assertEqual(get.call_count, 1)
