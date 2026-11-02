import tempfile
import time
import unittest
from unittest.mock import Mock
import requests
from skyhook_scout.api import ApiError, Client, ESI


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
