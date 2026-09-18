"""Kuryer xarajati — yetkazilgan har bir buyurtmadan avtomatik chiqim."""
import asyncio
import os
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import delivery_costs


def run(coro):
    return asyncio.run(coro)


class FeeTest(unittest.TestCase):
    def test_tashkent_courier(self):
        self.assertEqual(delivery_costs.fee_for("self"), 25_000)

    def test_regional_post(self):
        self.assertEqual(delivery_costs.fee_for("bts"), 5_000)
        self.assertEqual(delivery_costs.fee_for("emu"), 5_000)

    def test_buyer_paid_ride_costs_the_shop_nothing(self):
        # The buyer pays Yandex Taxi directly, so it must never be booked.
        self.assertEqual(delivery_costs.fee_for("yandex_taxi"), 0)

    def test_unknown_and_missing(self):
        self.assertEqual(delivery_costs.fee_for("yandex_market"), 0)
        self.assertEqual(delivery_costs.fee_for(None), 0)
        self.assertEqual(delivery_costs.fee_for(""), 0)


class BookingTest(unittest.TestCase):
    def _sweep(self, orders, booked_ok=True):
        book = AsyncMock(return_value=booked_ok)
        with patch.object(delivery_costs.database, "get_unbooked_delivery_orders",
                          AsyncMock(return_value=orders)), \
             patch.object(delivery_costs.database, "book_delivery_expense", book):
            result = run(delivery_costs.book_delivered_courier_costs())
        return result, book

    def test_nothing_to_book(self):
        (count, total), book = self._sweep([])
        self.assertEqual((count, total), (0, 0.0))
        book.assert_not_awaited()

    def test_books_each_method_at_its_own_rate(self):
        (count, total), book = self._sweep([
            {"id": 11, "delivery_method": "self"},
            {"id": 12, "delivery_method": "bts"},
            {"id": 13, "delivery_method": "emu"},
        ])
        self.assertEqual(count, 3)
        self.assertEqual(total, 35_000)
        amounts = {c.args[0]: c.args[2] for c in book.await_args_list}
        self.assertEqual(amounts, {11: 25_000, 12: 5_000, 13: 5_000})

    def test_row_names_the_order(self):
        _, book = self._sweep([{"id": 42, "delivery_method": "self"}])
        name = book.await_args_list[0].args[1]
        self.assertIn("#42", name)
        self.assertIn("Toshkent", name)

    def test_already_booked_is_not_counted(self):
        # The unique index rejects it; the sweep must not inflate the total.
        (count, total), _ = self._sweep(
            [{"id": 11, "delivery_method": "self"}], booked_ok=False)
        self.assertEqual((count, total), (0, 0.0))

    def test_method_outside_the_table_is_skipped(self):
        (count, total), book = self._sweep([
            {"id": 11, "delivery_method": "yandex_taxi"},
            {"id": 12, "delivery_method": "bts"},
        ])
        self.assertEqual((count, total), (1, 5_000))
        self.assertEqual([c.args[0] for c in book.await_args_list], [12])

    def test_only_paid_methods_are_queried(self):
        # The sweep must not pull every delivered order out of the database.
        fetch = AsyncMock(return_value=[])
        with patch.object(delivery_costs.database, "get_unbooked_delivery_orders", fetch), \
             patch.object(delivery_costs.database, "book_delivery_expense", AsyncMock()):
            run(delivery_costs.book_delivered_courier_costs())
        methods = fetch.await_args_list[0].args[0]
        self.assertEqual(sorted(methods), ["bts", "emu", "self"])

    def test_archive_is_not_swept(self):
        # Orders delivered before the feature went live must be left alone,
        # or their fees would all land on today and wreck one day's profit.
        fetch = AsyncMock(return_value=[])
        with patch.object(delivery_costs.database, "get_unbooked_delivery_orders", fetch), \
             patch.object(delivery_costs.database, "book_delivery_expense", AsyncMock()):
            run(delivery_costs.book_delivered_courier_costs())
        since = fetch.await_args_list[0].args[1]
        self.assertGreaterEqual(since, datetime(2026, 9, 18))

    def test_start_can_be_overridden(self):
        with patch.dict(os.environ, {"DELIVERY_COST_FROM": "2026-10-01T00:00:00"}):
            self.assertEqual(delivery_costs._start_from(), datetime(2026, 10, 1))

    def test_bad_override_falls_back(self):
        with patch.dict(os.environ, {"DELIVERY_COST_FROM": "kecha"}):
            self.assertEqual(delivery_costs._start_from(), datetime(2026, 9, 18, 17, 0))


if __name__ == "__main__":
    unittest.main(verbosity=1)
