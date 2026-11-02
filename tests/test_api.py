import tempfile
import time
import unittest
from unittest.mock import Mock
import requests
from skyhook_scout.api import ApiError, Client, ESI, Snapshot
from datetime import datetime, timezone


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.client = Client(self.temp.name)
        self.session = Mock()
        self.client.local.session = self.session

    def tearDown(self):
        self.temp.cleanup()

    def test_fresh_cache_does_not_make_request(self):
        self.client.cache.put(ESI + "/skyhooks/raidable", {"skyhooks": []}, time.time(), time.time() + 300)
        self.assertEqual(self.client.request("/skyhooks/raidable").data, {"skyhooks": []})
        self.session.request.assert_not_called()

    def test_expired_cache_revalidates_etag_and_304_keeps_data(self):
        self.client.cache.put(ESI + "/skyhooks/raidable", {"skyhooks": [1]}, time.time() - 400, 0, 'W/"tag"')
        self.session.request.return_value = Mock(status_code=304, headers={"Cache-Control": "max-age=300"})
        self.assertEqual(self.client.request("/skyhooks/raidable").data, {"skyhooks": [1]})
        self.assertEqual(self.session.request.call_args.kwargs["headers"]["If-None-Match"], 'W/"tag"')

    def test_failed_feed_uses_labelled_stale_cache(self):
        self.client.cache.put(ESI + "/skyhooks/raidable", {"skyhooks": []}, time.time() - 400, 0)
        self.session.request.side_effect = requests.Timeout("timeout")
        snapshot = self.client.request("/skyhooks/raidable", allow_stale=True)
        self.assertTrue(snapshot.stale)
        self.assertIn("timeout", snapshot.error)

    def test_rate_limit_sets_shared_cooldown(self):
        self.session.request.return_value = Mock(status_code=429, headers={"Retry-After": "60"})
        with self.assertRaises(ApiError):
            self.client.request("/skyhooks/raidable")
        with self.assertRaisesRegex(ApiError, "cooling down"):
            self.client.request("/universe/systems/30000001/")
        self.assertEqual(self.session.request.call_count, 1)

    def test_jump_counts_share_route_rules_deduplicate_systems_and_skip_name_lookups(self):
        expiry = datetime.fromtimestamp(time.time() + 600, timezone.utc).isoformat()
        hole = {"completed": True, "signature_type": "wormhole", "expires_at": expiry,
                "out_system_id": 31000005, "in_system_id": 30000001, "max_ship_size": "large"}
        def request(path, body=None, **kwargs):
            if path == "/route/31000005/30000001":
                self.assertEqual(body["preference"], "Shorter")
                self.assertEqual(len(body["connections"]), 2)
                return Snapshot({"route": [31000005, 30000001]}, time.time())
            raise AssertionError(f"Unexpected API request: {path}")
        self.client.request = Mock(side_effect=request)
        results = []
        self.client.jump_counts("Thera", [30000001, 30000001, 31000005], Snapshot([hole], time.time()),
                                progress=lambda item, _: results.append(item))
        self.assertEqual(results, [(30000001, 1, ""), (31000005, 0, "")])
        self.assertEqual(self.client.request.call_count, 1)
        self.client.request.reset_mock(side_effect=True)
        self.client.request.return_value = Snapshot({"route": [31000005, 30000002, 30000001]}, time.time())
        results.clear()
        self.client.jump_counts("Thera", [30000001], Snapshot([hole], time.time()), size=4,
                                progress=lambda item, _: results.append(item))
        self.assertEqual(self.client.request.call_args.args[1]["connections"], [])
        self.assertEqual(results, [(30000001, 2, "")])

    def test_jump_counts_mark_failures_unknown_and_continue(self):
        self.client.route_systems = Mock(side_effect=[ApiError("No route"), [31000005, 30000002]])
        results = []
        self.client.jump_counts("Thera", [30000001, 30000002], Snapshot([], time.time()),
                                progress=lambda item, _: results.append(item))
        self.assertEqual(results, [(30000001, None, "No route"), (30000002, 1, "")])

    def test_jump_counts_stop_after_cancellation_and_reject_stale_intel(self):
        self.client.route_systems = Mock(return_value=[31000005, 30000001])
        results = []
        self.client.jump_counts("Thera", [30000001, 30000002], Snapshot([], time.time()),
                                progress=lambda item, _: results.append(item), cancelled=lambda: bool(results))
        self.assertEqual(self.client.route_systems.call_count, 1)
        with self.assertRaisesRegex(ApiError, "15 minutes"):
            self.client.jump_counts("Thera", [30000001], Snapshot([], time.time() - 901))
