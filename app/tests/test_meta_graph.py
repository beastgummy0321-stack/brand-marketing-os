"""One GET per source page, fixed host/path, no token-bearing next URL replay."""

import json
import re
import unittest
from unittest.mock import patch

from app.meta import graph


class ExternalGraphTest(unittest.TestCase):
    def test_historical_structure_does_not_drop_archived_entities(self):
        def platform(url, *, params, headers):
            statuses = json.loads(params.get("effective_status", "[]"))
            if url.endswith("/adsets"):
                self.assertEqual(
                    set(statuses),
                    {
                        "ACTIVE",
                        "PAUSED",
                        "ARCHIVED",
                        "IN_PROCESS",
                        "WITH_ISSUES",
                        "CAMPAIGN_PAUSED",
                    },
                )
            rows = [{"id": "active"}]
            self.assertNotIn("DELETED", statuses)
            if "ARCHIVED" in statuses:
                rows.append({"id": "historical"})
            return {"data": rows}

        for section in ("campaigns", "adsets", "ads", "creatives"):
            with (
                self.subTest(section=section),
                patch.object(graph, "fetch_page", side_effect=platform),
            ):
                page = graph.external_page("secret", "1", section, native_id="3")
                self.assertIn("historical", [row["id"] for row in page["data"]])

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

    def test_base64_padding_cursor_is_parameter_not_url(self):
        with patch.object(graph, "fetch_page", return_value={"data": []}) as fetch:
            graph.external_page("secret", "1", "campaigns", cursor="opaque/+=")
        self.assertEqual(fetch.call_args.kwargs["params"]["after"], "opaque/+=")
        self.assertEqual(fetch.call_args.args[0], graph.GRAPH_BASE_URL + "/act_1/campaigns")

    def test_transport_timeout_remains_retryable_after_sanitization(self):
        with patch.object(graph.httpx, "get", side_effect=graph.httpx.ReadTimeout("secret-url")):
            with self.assertRaises(graph.GraphError) as caught:
                graph.external_page("secret", "1", "monthly", start="2026-09-01", end="2026-09-19")
        self.assertTrue(caught.exception.retryable)
        self.assertNotIn("secret", str(caught.exception))

    def test_monthly_transport_repeats_account_scope_on_every_page(self):
        with patch.object(graph.httpx, "get") as get:
            get.return_value.json.side_effect = [
                {"data": [], "paging": {"next": "https://ignored/", "cursors": {"after": "next"}}},
                {"data": []},
            ]
            first = graph.external_page(
                "secret", "1", "monthly", start="2026-09-01", end="2026-09-19"
            )
            graph.external_page(
                "secret",
                "1",
                "monthly",
                cursor=first["cursor"],
                start="2026-09-01",
                end="2026-09-19",
            )
        for call in get.call_args_list:
            self.assertEqual(call.args[0], graph.GRAPH_BASE_URL + "/act_1/insights")
            params = call.kwargs["params"]
            self.assertEqual(
                params["fields"],
                "account_id,account_currency,campaign_id,date_start,date_stop,spend",
            )
            self.assertEqual(params["level"], "campaign")
            self.assertEqual(str(params["time_increment"]), "1")
            self.assertEqual(
                json.loads(params["time_range"]), {"since": "2026-09-01", "until": "2026-09-19"}
            )
        self.assertEqual(get.call_args_list[1].kwargs["params"]["after"], "next")

    def test_single_objects_use_fixed_node_get_not_campaign_listing(self):
        for kind in ("ad", "adset", "campaign"):
            with patch.object(
                graph, "fetch_page", return_value={"id": "3", "account_id": "1"}
            ) as fetch:
                result = graph.external_page("secret", "1", kind, native_id="3")
            self.assertEqual(fetch.call_args.args[0], graph.GRAPH_BASE_URL + "/3")
            self.assertEqual(result["data"][0]["id"], "3")

    def test_launch_settings_readback_fields_ride_the_single_object_reads(self):
        expected = {
            "campaign": {"bid_strategy"},
            "adset": {"optimization_goal", "bid_strategy", "targeting", "promoted_object"},
            "ad": {"url_tags"},
        }
        for kind, fields in expected.items():
            with patch.object(
                graph, "fetch_page", return_value={"id": "3", "account_id": "1"}
            ) as fetch:
                graph.external_page("secret", "1", kind, native_id="3")
            requested = set(re.findall(r"[a-z_]+", fetch.call_args.kwargs["params"]["fields"]))
            self.assertLessEqual(fields, requested, kind)

    def test_pixel_list_is_one_account_edge_read_with_id_and_name(self):
        payload = {"data": [{"id": "7", "name": "官網像素"}]}
        with patch.object(graph, "fetch_page", return_value=payload) as fetch:
            page = graph.external_page("secret", "1", "pixels")
        self.assertEqual(fetch.call_args.args[0], graph.GRAPH_BASE_URL + "/act_1/adspixels")
        self.assertEqual(fetch.call_args.kwargs["params"]["fields"], "id,name")
        self.assertNotIn("effective_status", fetch.call_args.kwargs["params"])
        self.assertEqual(page["data"], payload["data"])
