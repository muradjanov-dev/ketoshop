"""Kuryer doskasi: UzPost bo'limi va indeksi kartochkada (egasi, 2026-11-26)."""
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")


class UzPostOfficeOnBoardTest(unittest.TestCase):
    """Egasi, 2026-11-26: "bazi uzpost buyurtmalarida index chiqmayapti"."""

    def test_card_carries_the_office_and_missing_ones_are_found_from_the_pin(self):
        import asyncio
        from unittest.mock import AsyncMock, patch
        import courier_board as cb
        import database
        import uzpost
        orders = [
            {"id": 1, "delivery_method": "uzpost", "post_office": None, "latitude": 40.1, "longitude": 65.3},
            {"id": 2, "delivery_method": "uzpost", "post_office": "141600 — Urgut", "latitude": 39.4,
             "longitude": 67.2},
            {"id": 3, "delivery_method": "uzpost", "post_office": None, "latitude": None, "longitude": None},
            {"id": 4, "delivery_method": "self", "post_office": None, "latitude": 41.3, "longitude": 69.2},
        ]
        office = {"index": "210100", "name": "Buxoro Pochtamt", "address": "Buxoro"}
        save = AsyncMock()
        with patch.object(uzpost, "nearest_office", AsyncMock(return_value=office)) as near, \
                patch.object(database, "set_order_post_office", save):
            n = asyncio.run(cb.fill_post_offices(orders))
        self.assertEqual(n, 1)
        near.assert_awaited_once_with(40.1, 65.3)
        save.assert_awaited_once_with(1, "210100 — Buxoro Pochtamt, Buxoro")
        self.assertEqual(orders[0]["post_office"], "210100 — Buxoro Pochtamt, Buxoro")
        self.assertIsNone(orders[2]["post_office"])                 # lokatsiyasiz — admin aniqlaydi
        self.assertEqual(cb._card(dict(orders[1], status="new", items="[]"))["post_office"], "141600 — Urgut")
