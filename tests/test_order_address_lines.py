"""Admin buyurtma kartochkalarida manzil (egasi, 2026-10-13): "birinchisida
manzil nomi bor, ikkinchisida yo'q, boshqalarida ham manzil nomi bo'lsin va
yandex maps da havola ham bo'lsin"."""
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import courier_board
import order_admin_feed as feed

ORDER = {
    "id": 632, "status": "confirmed", "customer_name": "Дилноза", "phone": "+998992288314",
    "address": "📍 41.357019, 69.275420",
    "address_note": "М.Улугбек тум Геофизика Хислат 5уй 12 хонадон",
    "latitude": 41.357019, "longitude": 69.275420,
    "items": [{"name": "Bodom uni 1000gr", "quantity": 2, "price": 153000}],
    "total": 802800,
}
URL = "https://yandex.uz/maps/?pt=69.275420,41.357019&z=17&l=map"


class MapUrlTest(unittest.TestCase):
    def test_from_columns(self):
        self.assertEqual(feed.map_url(ORDER), URL)

    def test_from_the_stored_address_when_columns_are_empty(self):
        for address in ("41.357019, 69.275420", "📍 41.357019, 69.275420",
                        "📍 41.357019, 69.275420 — Mirzo Ulug'bek, Geofizika"):
            order = dict(ORDER, latitude=None, longitude=None, address=address)
            self.assertEqual(feed.map_url(order), URL, address)

    def test_no_pin_no_link(self):
        for address in ("Chilonzor 9-kvartal", "Toshkent, Yunusobod 4, 12-uy"):
            self.assertIsNone(feed.map_url(dict(ORDER, latitude=None, longitude=None, address=address)))

    def test_board_reads_the_bot_format_too(self):
        pin = courier_board.order_pin({"address": "📍 41.3, 69.2 — Chilonzor"})
        self.assertEqual(pin, (41.3, 69.2))


class StatusCardTest(unittest.TestCase):
    def card(self, order=ORDER, lang="uz"):
        return feed.build_card(order, lang, title="status_title", by="Sayt — Kuryer doskasi",
                               old_status="pending", new_status="confirmed")

    LINK = f'🗺 <a href="{URL.replace("&", "&amp;")}">Yandex xaritada ochish</a>'

    def test_link_instead_of_coordinates(self):
        # Owner, 2026-10-14: "41.018332, 69.676414 shuni o'rniga yandex xarita
        # havolasi chiqara olamizmi?"
        text = self.card()
        self.assertIn(f"📍 {self.LINK}", text)
        self.assertNotIn("41.357019", text.replace(URL.replace("&", "&amp;"), ""))
        self.assertNotIn("📍 📍", text)
        self.assertIn("📝 М.Улугбек тум Геофизика Хислат 5уй 12 хонадон", text)

    def test_street_stays_readable_next_to_the_link(self):
        text = self.card(dict(ORDER, address="📍 41.357019, 69.275420 — Mirzo Ulug'bek, Geofizika"))
        self.assertIn(f"📍 Mirzo Ulug'bek, Geofizika · {self.LINK}", text)

    def test_order_of_lines(self):
        lines = self.card().split("\n")
        i = next(n for n, l in enumerate(lines) if l.startswith("📍"))
        self.assertTrue(lines[i + 1].startswith("📝"))
        self.assertFalse(any(l.startswith("🗺") for l in lines))   # no separate map line

    def test_languages(self):
        self.assertIn("Открыть в Яндекс Картах", self.card(lang="ru"))
        self.assertIn("Yandex харитада очиш", self.card(lang="uz_cyr"))

    def test_buyer_text_is_escaped(self):
        text = self.card(dict(ORDER, address_note="Uy <5> & 12"))
        self.assertIn("📝 Uy &lt;5&gt; &amp; 12", text)

    def test_without_note_or_pin(self):
        text = self.card(dict(ORDER, address_note=None, latitude=None, longitude=None,
                              address="Chilonzor 9-kvartal"))
        self.assertIn("📍 Chilonzor 9-kvartal", text)
        self.assertNotIn("📝", text)
        self.assertNotIn("🗺", text)


FULL = dict(ORDER, user_id=555, secondary_phone="+998901112233", delivery_method="self",
            payment_method="cash", source="bot")


class CustomerBlockTest(unittest.TestCase):
    """Everything the new-order card says about the buyer, on every status card."""

    def card(self, order=FULL, **kw):
        return feed.build_card(order, "uz", title="status_title", by="Nodir",
                               old_status="pending", new_status=order.get("status", "confirmed"), **kw)

    def test_all_lines_in_order(self):
        text = self.card(history="🔁 <b>2-buyurtmasi</b> (oldingi 1 tasi yetkazilgan)\n",
                         contact='<a href="https://t.me/dilnoza">@dilnoza</a>')
        lines = text.split("\n")
        starts = ["👤 Дилноза", "🔁 <b>2-buyurtmasi</b>", "📱 +998992288314", "📞 +998901112233",
                  "💬 <a href=", "📍 🗺 <a href=", "📝 М.Улугбек",
                  "🚚 Yetkazib berish:", "💵 To'lov: Naqd — ⏳"]
        found = [next(i for i, l in enumerate(lines) if l.startswith(s)) for s in starts]
        self.assertEqual(found, sorted(found))
        self.assertEqual(found, list(range(found[0], found[0] + len(starts))))   # one block

    def test_payment_follows_the_status(self):
        self.assertIn("💵 To'lov: Naqd — ✅ To'langan", self.card(dict(FULL, status="delivered")))
        self.assertNotIn("To'lov", self.card(dict(FULL, status="cancelled")))
        self.assertIn("Karta orqali", self.card(dict(FULL, payment_method="online")))

    def test_ai_card_order_waiting_for_money_says_unpaid(self):
        from locales import get_text
        unpaid = dict(FULL, address_note="Hislat 5-uy · To'lov: KARTA (chek kutilmoqda)")
        self.assertIn(get_text("pay_card_unpaid", "uz"), self.card(unpaid))
        self.assertNotIn("Yetkazib berishda to'lanadi", self.card(unpaid))
        self.assertIn(get_text("pay_card_cheque", "uz"), self.card(dict(unpaid, cheque_file_id="F")))

    def test_send_all_adds_history_and_contact(self):
        import asyncio
        from unittest.mock import AsyncMock, patch
        bot = AsyncMock()
        with patch("database.get_order", AsyncMock(return_value=FULL)), \
             patch("database.get_user", AsyncMock(return_value={"username": "dilnoza"})), \
             patch("database.get_user_language", AsyncMock(return_value="uz")), \
             patch("database.get_order_history_position",
                   AsyncMock(return_value={"nth": 2, "delivered": 1, "cancelled": 0}), create=True), \
             patch.object(feed, "ADMIN_IDS", {1}):
            asyncio.run(feed._send_all(bot, 632, title="status_title", by="Nodir",
                                       old_status="pending", new_status="confirmed"))
        text = bot.send_message.call_args.args[1]
        self.assertIn("2-buyurtmasi", text)
        self.assertIn('💬 <a href="https://t.me/dilnoza">@dilnoza</a>', text)

    def test_typed_by_admin_has_no_buyer_chat_or_history(self):
        import asyncio
        from unittest.mock import AsyncMock, patch
        bot = AsyncMock()
        manual = dict(FULL, source="manual", user_id=1)
        with patch("database.get_order", AsyncMock(return_value=manual)), \
             patch("database.get_user", AsyncMock(return_value={"username": "admin"})) as get_user, \
             patch("database.get_user_language", AsyncMock(return_value="uz")), \
             patch.object(feed, "ADMIN_IDS", {1}):
            asyncio.run(feed._send_all(bot, 632, title="manual_title", by="Nodir"))
        text = bot.send_message.call_args.args[1]
        self.assertNotIn("💬", text)
        self.assertNotIn("buyurtmasi", text)
        get_user.assert_not_called()


class CourierBoardCardTest(unittest.TestCase):
    """Kuryer paneli: the same buyer facts as the bot card."""

    def card(self, **row):
        base = dict(FULL, status="confirmed", created_at=None, buyer_username="dilnoza")
        return courier_board._card(dict(base, **row))

    def test_history_from_the_board_query(self):
        c = self.card(hist_nth=2, hist_delivered=1, hist_cancelled=0)
        self.assertEqual(c["history"], {"nth": 2, "delivered": 1, "cancelled": 0})

    def test_manual_order_has_no_history(self):
        self.assertIsNone(self.card(source="manual", hist_nth=None)["history"])

    def test_buyer_fields_reach_the_panel(self):
        c = self.card(hist_nth=1, hist_delivered=0, hist_cancelled=0)
        for key in ("address_note", "secondary_phone", "latitude", "longitude",
                    "delivery_method", "payment_method", "username", "phone"):
            self.assertIn(key, c)
        self.assertEqual(c["address_note"], FULL["address_note"])


if __name__ == "__main__":
    unittest.main()
