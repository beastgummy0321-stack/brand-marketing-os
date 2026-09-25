"""Exercise the actual transport seam; every request is intercepted, never live."""

import json
import unittest
from datetime import date
from unittest.mock import Mock, patch
from urllib.parse import urlencode

import httpx

from app.meta import graph

BASE = graph.GRAPH_BASE_URL
HEADERS = {"Authorization": "Bearer private-token"}


class MetaReadPolicyTest(unittest.TestCase):
    def test_all_existing_read_shapes_reach_transport_without_credentials_in_url(self):
        reads = [
            lambda: graph.list_ad_accounts("private-token"),
            lambda: graph.list_campaigns("private-token", "1"),
            lambda: graph.list_ad_sets("private-token", "2"),
            lambda: graph.list_ads("private-token", "3"),
            lambda: graph.fetch_budgets("private-token", ["2"]),
            lambda: graph.fetch_ad_creatives("private-token", ["4"]),
            lambda: graph.list_entity_insights("private-token", "1", "ad",
                                               date(2026, 9, 1), date(2026, 9, 2)),
        ]
        reads.extend(
            lambda section=section: graph.external_page(
                "private-token", "1", section, native_id="2", level="ad",
                start="2026-09-01", end="2026-09-02")
            for section in graph._EXTERNAL_FIELDS
        )
        with patch.object(graph.httpx, "get") as get:
            get.return_value.json.return_value = {"id": "2", "data": []}
            for read in reads:
                read()
            self.assertEqual(get.call_count, len(reads))
            for call in get.call_args_list:
                self.assertNotIn("private-token", call.args[0])
                self.assertNotIn("access_token", call.kwargs["params"])
                self.assertFalse(call.kwargs["follow_redirects"])

    def test_get_mutation_and_request_injection_never_reach_network(self):
        cases = [
            (BASE + "/2", {"method": "DELETE"}, HEADERS),
            (BASE + "/2?method=POST", {}, HEADERS),
            (BASE + "/2?%6dethod=DELETE", {}, HEADERS),
            (BASE + "/2", {"status": "ACTIVE"}, HEADERS),
            (BASE + "/2", {"batch": "[]"}, HEADERS),
            (BASE + "/2", {"fields": "id,access_token"}, HEADERS),
            (BASE + "/2", {"fields": "creative.limit(100){id}"}, HEADERS),
            (BASE + "/2", {"fields": "id", "limit": 10000}, HEADERS),
            (BASE + "/2", {"fields": "id"}, {**HEADERS, "X-HTTP-Method-Override": "DELETE"}),
            (BASE + "/2", {"fields": "id"}, {**HEADERS, "Host": "evil.test"}),
            (BASE + "/2?fields=id&fields=name", None, HEADERS),
            (BASE + "/2?access_token=another-token", None, HEADERS),
        ]
        bad_paths = [
            "https://evil.test/v26.0/2", "http://graph.facebook.com/v26.0/2",
            "https://graph.facebook.com.evil.test/v26.0/2",
            "https://evil.test@graph.facebook.com/v26.0/2",
            "https://graph.facebook.com:443/v26.0/2", BASE + "/2#ignored",
            BASE + "/2/ads/../delete", BASE + "/2%2fads", BASE + "/2/delete",
            BASE + "/me/permissions", BASE + "/act_1/adcreatives", BASE + "/２",
        ]
        cases.extend((url, {"fields": "id"}, HEADERS) for url in bad_paths)
        with patch.object(graph.httpx, "get") as get:
            for url, params, headers in cases:
                with self.subTest(url=url, params=params):
                    with self.assertRaises(graph.GraphError) as caught:
                        graph.fetch_page(url, params=params, headers=headers)
                    self.assertNotIn("private-token", str(caught.exception))
            get.assert_not_called()

    def test_paging_stays_on_original_read_and_strips_echoed_token(self):
        responses = [
            {"data": [{"account_id": "1"}], "paging": {"next":
                BASE + "/me/adaccounts?after=cursor%2F%2B%3D&access_token=private-token"}},
            {"data": [{"account_id": "2"}]},
        ]
        with patch.object(graph.httpx, "get") as get:
            get.side_effect = [Mock(json=Mock(return_value=body)) for body in responses]
            rows = graph.list_ad_accounts("private-token")
            self.assertEqual([r["account_id"] for r in rows], ["1", "2"])
            self.assertEqual(get.call_args.args[0], BASE + "/me/adaccounts")
            self.assertEqual(get.call_args.kwargs["params"]["after"], "cursor/+=")
            self.assertEqual(get.call_args.kwargs["params"]["limit"], "100")
            self.assertNotIn("access_token", get.call_args.kwargs["params"])

    def test_untrusted_paging_cannot_switch_object_or_operation(self):
        for next_url in (
            "https://evil.test/?access_token=private-token", BASE + "/2?after=a",
            BASE + "/me/adaccounts?after=a&method=DELETE",
            BASE + "/me/adaccounts?after=a&fields=id",
            BASE + "/me/adaccounts?after=a&limit=200",
        ):
            with self.subTest(next_url=next_url), patch.object(graph.httpx, "get") as get:
                get.return_value.json.return_value = {"data": [], "paging": {"next": next_url}}
                with self.assertRaises(graph.GraphError):
                    graph.list_ad_accounts("private-token")
                self.assertEqual(get.call_count, 1)

    def test_pagination_accepts_equivalent_json_but_never_changes_range(self):
        original = {"since": "2026-09-01", "until": "2026-09-02"}
        for changed in (False, True):
            follow = {
                "after": "next", "time_range": json.dumps({
                    "until": "2026-09-03" if changed else "2026-09-02",
                    "since": "2026-09-01"}, separators=(",", ":")),
                "action_attribution_windows": '["7d_click","1d_view"]',
            }
            responses = [
                {"data": [], "paging": {"next": BASE + "/act_1/insights?" + urlencode(follow)}},
                {"data": []},
            ]
            with self.subTest(changed=changed), patch.object(graph.httpx, "get") as get:
                get.side_effect = [Mock(json=Mock(return_value=body)) for body in responses]
                if changed:
                    with self.assertRaises(graph.GraphError):
                        graph.list_entity_insights("private-token", "1", "ad",
                                                   date(2026, 9, 1), date(2026, 9, 2))
                    self.assertEqual(get.call_count, 1)
                else:
                    graph.list_entity_insights("private-token", "1", "ad",
                                               date(2026, 9, 1), date(2026, 9, 2))
                    self.assertEqual(get.call_count, 2)
                    self.assertEqual(json.loads(get.call_args.kwargs["params"]["time_range"]),
                                     original)

    def test_provider_and_transport_errors_never_echo_credentials(self):
        with patch.object(graph.httpx, "get") as get:
            get.return_value.json.return_value = {
                "error": {"code": 190, "message": "private-token https://secret.test"}}
            with self.assertRaises(graph.GraphError) as caught:
                graph.list_ad_accounts("private-token")
            self.assertEqual(caught.exception.code, 190)
            self.assertNotIn("private-token", str(caught.exception))
            self.assertNotIn("secret.test", str(caught.exception))
            for error in (httpx.ConnectError("private-token"),
                          json.JSONDecodeError("private-token", "private-token", 0)):
                get.side_effect = error
                with self.assertRaises(graph.GraphError) as caught:
                    graph.fetch_page(BASE + "/2", params={"fields": "id"}, headers=HEADERS)
                self.assertNotIn("private-token", str(caught.exception))
                self.assertTrue(caught.exception.__suppress_context__)

    def test_runaway_paging_still_has_a_hard_limit(self):
        count = 0

        def page(*args, **kwargs):
            nonlocal count
            count += 1
            return Mock(json=Mock(return_value={"data": [], "paging": {
                "next": BASE + f"/me/adaccounts?after={count}"}}))

        with (
            patch.object(graph, "_MAX_PAGES", 3),
            patch.object(graph.httpx, "get", side_effect=page),
        ):
            with self.assertRaises(graph.GraphError):
                graph.list_ad_accounts("private-token")
        self.assertEqual(count, 3)


class LaunchSettingsReadPolicyTest(unittest.TestCase):
    """F29-I07: the launch-settings readback widens the policy by exactly its fields and one
    path; every other field, edge and method is still refused before the network."""

    def test_launch_settings_fields_and_pixel_list_reach_transport(self):
        allowed = [
            (BASE + "/act_1/adspixels", {"fields": "id,name", "limit": 100}),
            (
                BASE + "/2",
                {"fields": "id,optimization_goal,bid_strategy,targeting,promoted_object"},
            ),
            (BASE + "/2", {"fields": "targeting{age_min,age_max,genders,geo_locations{countries},"
                           "publisher_platforms,facebook_positions,instagram_positions,"
                           "messenger_positions},promoted_object{pixel_id,custom_event_type}"}),
            (BASE + "/2", {"fields": "creative{url_tags}"}),
        ]
        with patch.object(graph.httpx, "get") as get:
            get.return_value.json.return_value = {"data": []}
            for url, params in allowed:
                with self.subTest(url=url, params=params):
                    graph.fetch_page(url, params=params, headers=HEADERS)
            self.assertEqual(get.call_count, len(allowed))

    def test_every_other_field_and_path_is_still_refused(self):
        refused = [
            (BASE + "/2", {"fields": "targeting{flexible_spec}"}),
            (BASE + "/2", {"fields": "targeting{custom_audiences}"}),
            (BASE + "/2", {"fields": "promoted_object{application_id}"}),
            (BASE + "/2", {"fields": "id,bid_amount"}),
            (BASE + "/2", {"fields": "id,daily_min_spend_target"}),
            (BASE + "/2", {"fields": "creative{url_tags,effective_object_story_id}"}),
            (BASE + "/act_1/adspixels", {"fields": "id,code"}),
            (BASE + "/act_1/adspixels", {"fields": "id,name", "method": "POST"}),
            (BASE + "/act_1/adspixels/2", {"fields": "id"}),
            (BASE + "/act_1/customaudiences", {"fields": "id,name"}),
            (BASE + "/act_1/adsets", {"fields": "id,targeting"}),
            (BASE + "/2/stats", {"fields": "id"}),
            (BASE + "/2/shared_accounts", {"fields": "id"}),
            (BASE + "/me/adspixels", {"fields": "id,name"}),
            (BASE + "/2", {"fields": "id,targeting", "targeting": "{}"}),
        ]
        with patch.object(graph.httpx, "get") as get:
            for url, params in refused:
                with self.subTest(url=url, params=params):
                    with self.assertRaises(graph.GraphError):
                        graph.fetch_page(url, params=params, headers=HEADERS)
            get.assert_not_called()
