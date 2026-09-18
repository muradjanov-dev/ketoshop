"""Do'kon podiumi: har kuni boshqa mahsulotlar, lekin hammasi haqiqiy top."""
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

from database import rotate_daily_window

POOL = [{"id": i, "name": f"P{i}"} for i in range(1, 13)]   # 12, best first


def ids(rows):
    return [r["id"] for r in rows]


class WindowTest(unittest.TestCase):
    def test_returns_exactly_limit(self):
        self.assertEqual(len(rotate_daily_window(POOL, 3, day=100)), 3)

    def test_same_day_is_stable(self):
        # A buyer who reloads the home page must not see the podium reshuffle.
        self.assertEqual(ids(rotate_daily_window(POOL, 3, day=100)),
                         ids(rotate_daily_window(POOL, 3, day=100)))

    def test_next_day_shows_different_products(self):
        a = set(ids(rotate_daily_window(POOL, 3, day=100)))
        b = set(ids(rotate_daily_window(POOL, 3, day=101)))
        self.assertFalse(a & b, f"{a} and {b} overlap")

    def test_whole_pool_gets_its_turn(self):
        seen = set()
        for day in range(100, 104):          # 12 products / 3 per day
            seen |= set(ids(rotate_daily_window(POOL, 3, day=day)))
        self.assertEqual(seen, {p["id"] for p in POOL})

    def test_window_is_ranked_within_itself(self):
        # The podium hands out 🥇🥈🥉, so the slice has to come back in
        # popularity order — otherwise the medals are simply wrong.
        for day in range(100, 108):
            got = ids(rotate_daily_window(POOL, 3, day=day))
            self.assertEqual(got, sorted(got), f"day {day}: {got}")

    def test_small_shop_is_returned_whole(self):
        for n in (0, 1, 2, 3):
            pool = POOL[:n]
            self.assertEqual(ids(rotate_daily_window(pool, 3, day=100)), ids(pool))

    def test_pool_of_four_still_rotates(self):
        a = ids(rotate_daily_window(POOL[:4], 3, day=100))
        b = ids(rotate_daily_window(POOL[:4], 3, day=101))
        self.assertNotEqual(a, b)
        self.assertEqual(len(a), 3)

    def test_no_duplicates_in_a_window(self):
        for day in range(100, 120):
            got = ids(rotate_daily_window(POOL[:5], 3, day=day))
            self.assertEqual(len(set(got)), len(got), f"day {day}: {got}")


if __name__ == "__main__":
    unittest.main(verbosity=1)
