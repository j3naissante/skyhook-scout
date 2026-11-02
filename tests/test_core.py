from datetime import datetime
import unittest
from skyhook_scout.core import (active_connections, connection_edges, describe_route, display_time,
    estimate_raid, matches, status, timestamp)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.now = timestamp("2026-11-02T12:00:00Z")
        self.hook = {"planet_id": 1, "solar_system_id": 30000001, "system": "XW-JHT",
                     "planet": "XW-JHT I", "planet_type": "Lava", "region": "Branch",
                     "theft_vulnerability": {"start": "2026-11-02T12:00:00Z", "end": "2026-11-02T14:00:00Z"}}
        self.hole = {"completed": True, "signature_type": "wormhole", "expires_at": "2026-11-02T13:00:00Z",
                     "in_system_id": 30000001, "out_system_id": 31000005, "max_ship_size": "medium"}

    def test_window_boundaries(self):
        self.assertEqual(status(self.hook, self.now - 1), "Upcoming")
        self.assertEqual(status(self.hook, self.now), "Open now")
        self.assertEqual(status(self.hook, self.now + 7200), "Expired")

    def test_combined_filters(self):
        self.assertTrue(matches(self.hook, "xw-jht", "Branch", "Lava", "Open now", self.now))
        self.assertFalse(matches(self.hook, "", "Catch", "Lava", "Open now", self.now))
        self.assertFalse(matches(self.hook, "", "Branch", "Ice", "Open now", self.now))
        self.assertFalse(matches(self.hook, "", "Branch", "Lava", "Upcoming", self.now))
        self.assertTrue(matches(self.hook, region="Branch", planet_type="Lava", planet="XW-JHT I", now=self.now))
        self.assertFalse(matches(self.hook, planet="XW-JHT II", now=self.now))

    def test_display_mode_does_not_change_absolute_time(self):
        self.assertEqual(display_time(self.now, False), "12:00 UTC")
        self.assertEqual(display_time(self.now, False, False), "12:00")
        self.assertEqual(display_time(self.now, True, False), datetime.fromtimestamp(self.now).astimezone().strftime("%H:%M"))

    def test_connections_exclude_expired_unconfirmed_and_unknown_chains(self):
        variants = [self.hole, {**self.hole, "expires_at": "2026-11-02T11:00:00Z"},
                    {**self.hole, "completed": False}, {**self.hole, "in_system_id": 31000999},
                    {**self.hole, "max_ship_size": "unknown"}, {**self.hole, "expires_at": "invalid"}]
        self.assertEqual(active_connections(variants, 2, self.now), [self.hole])
        self.assertEqual(active_connections(variants, 4, self.now), [])

    def test_route_counts_edges_in_both_directions(self):
        self.assertEqual(len(connection_edges([self.hole])), 2)
        result = describe_route([30000002, 30000001, 31000005], [self.hole])
        self.assertEqual((result["gates"], result["wormholes"]), (1, 1))
        self.assertEqual(describe_route([30000001], [])["hops"], [])

    def test_feasibility_waits_for_opening_and_includes_buffer(self):
        self.assertTrue(estimate_raid(5, self.hook, now=self.now)[1])
        self.assertFalse(estimate_raid(200, self.hook, now=self.now)[1])
        self.assertFalse(estimate_raid(1, self.hook, raid=121, buffer=0, now=self.now - 7200)[1])


if __name__ == "__main__":
    unittest.main()
