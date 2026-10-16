"""«Kelganda xabar bering» (egasi, 2026-10-14): tugagan mahsulotni so'ragan
mijozga mahsulot qaytganda "Siz qiziqqan mahsulot do'konimizga qaytdi"
xabari boradi. Telegram va bazaga ulanmasdan — hamma yuborish mock."""
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

from aiogram.exceptions import TelegramForbiddenError

import database
import product_card
import restock_notify
import stock_alerts
import webapp_server
from locales import get_text


def product(pid=5, quantity=0, **kw):
    return {"id": pid, "name": "Chia urug'i 300gr", "name_ru": None, "description": "Tavsif",
            "description_ru": None, "price": 50000, "discount_percent": 0, "discount_until": None,
            "unit": "piece", "quantity": quantity, "category": "seeds", "photo_id": "PHOTO",
            "seller_name": "", "is_active": 1, "b2b_only": False, **kw}


class SubscribeTest(unittest.IsolatedAsyncioTestCase):
    async def status(self, p, added=True, free=None):
        shelf = float((p or {}).get("quantity") or 0)
        view = {5: {"shelf": shelf, "held": shelf - (shelf if free is None else free),
                    "free": shelf if free is None else free}}
        with patch.object(database, "get_product", AsyncMock(return_value=p)), \
             patch.object(database, "stock_view", AsyncMock(return_value=view)), \
             patch.object(database, "add_restock_wait", AsyncMock(return_value=added)) as add:
            return await restock_notify.subscribe(7, 5, "ru", "site"), add

    async def test_sold_out_product_goes_on_the_list_once(self):
        status, add = await self.status(product())
        self.assertEqual(status, "added")
        add.assert_awaited_once_with(7, 5, "ru", "site")
        status, _ = await self.status(product(), added=False)
        self.assertEqual(status, "already")

    async def test_a_product_held_in_other_carts_can_be_waited_for(self):
        # Savat broni (2026-10-16): 3 on the shelf, all in other buyers' carts.
        status, add = await self.status(product(quantity=3), free=0)
        self.assertEqual(status, "added")
        add.assert_awaited_once_with(7, 5, "ru", "held")

    async def test_nothing_to_wait_for(self):
        status, add = await self.status(product(quantity=3))
        self.assertEqual(status, "in_stock")
        add.assert_not_awaited()
        for p in (None, product(is_active=0), product(b2b_only=True)):
            status, add = await self.status(p)
            self.assertEqual(status, "not_found")
            add.assert_not_awaited()


class RunOnceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.sent = []

        async def fake_send(bot, user_id, p, lang, source=None):
            self.sent.append((user_id, p["id"], lang))
            self.sources.append(source)
            return user_id != 13            # 13 blocked the bot

        self.sources = []
        self.free = {}                      # product_id -> free for the waiter (default: shelf)

        self.patches = [
            patch.object(restock_notify, "_quiet_now", lambda: False),
            patch.object(restock_notify, "_send_card", fake_send),
            patch.object(restock_notify, "_tell_admins", AsyncMock()),
            patch.object(restock_notify, "SEND_DELAY", 0),
            patch.object(database, "get_user_languages", AsyncMock(return_value={11: "uz_cyr"})),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    async def run_with(self, due, products, claim=lambda wid: True):
        def view(pids, user_id=None):
            pid = pids[0]
            shelf = float(products[pid].get("quantity") or 0)
            return {pid: {"shelf": shelf, "free": self.free.get(pid, shelf)}}
        with patch.object(database, "get_restock_due", AsyncMock(return_value=due)), \
             patch.object(database, "get_product", AsyncMock(side_effect=lambda pid: products.get(pid))), \
             patch.object(database, "stock_view", AsyncMock(side_effect=view)), \
             patch.object(database, "claim_restock_notice", AsyncMock(side_effect=claim)):
            return await restock_notify.run_once(MagicMock())

    async def test_band_waiters_hear_when_it_frees_up_by_any_path(self):
        # Owner, 2026-10-16: the hold ran out, its holder let it go, or the admin
        # added stock before the 6 h — whoever asked hears it either way.
        due = [{"id": 1, "user_id": 11, "product_id": 5, "lang": "uz", "source": "held"}]
        self.free = {5: 0}                  # still all in another cart: nothing yet
        stats = await self.run_with(due, {5: product(quantity=3)})
        self.assertEqual((self.sent, stats["skipped"]), ([], 1))
        self.free = {5: 2}                  # admin added 2 while the hold is still on
        stats = await self.run_with(due, {5: product(quantity=5)})
        self.assertEqual(self.sent, [(11, 5, "uz_cyr")])
        self.assertEqual(self.sources, ["held"])

    async def test_everyone_waiting_hears_once_in_their_language(self):
        due = [{"id": 1, "user_id": 11, "product_id": 5, "lang": "uz"},
               {"id": 2, "user_id": 12, "product_id": 5, "lang": "ru"},
               {"id": 3, "user_id": 13, "product_id": 5, "lang": "uz"}]
        stats = await self.run_with(due, {5: product(quantity=4)})
        self.assertEqual(self.sent, [(11, 5, "uz_cyr"), (12, 5, "ru"), (13, 5, "uz")])
        self.assertEqual((stats["sent"], stats["failed"]), (2, 1))
        line = restock_notify._tell_admins.await_args.args[1]
        self.assertIn("Chia urug&#x27;i 300gr", line)   # HTML-escaped, like /ombor
        self.assertIn("3 ta mijozga", line)
        self.assertIn("1 tasi botni bloklagan", line)

    async def test_claimed_elsewhere_or_sold_out_again_is_skipped(self):
        due = [{"id": 1, "user_id": 11, "product_id": 5, "lang": "uz"},
               {"id": 2, "user_id": 12, "product_id": 6, "lang": "uz"}]
        stats = await self.run_with(due, {5: product(quantity=2), 6: product(pid=6, quantity=0)},
                                    claim=lambda wid: False)
        self.assertEqual(self.sent, [])
        self.assertEqual(stats["skipped"], 2)
        restock_notify._tell_admins.assert_not_awaited()

    async def test_quiet_hours_send_nothing(self):
        with patch.object(restock_notify, "_quiet_now", lambda: True), \
             patch.object(database, "get_restock_due", AsyncMock()) as due:
            stats = await restock_notify.run_once(MagicMock())
        due.assert_not_awaited()
        self.assertEqual(stats["sent"], 0)


class SendCardTest(unittest.IsolatedAsyncioTestCase):
    async def send(self, bot):
        with patch("gamification.buyer_rate", AsyncMock(return_value=None)), \
             patch.object(product_card, "get_product_rating", AsyncMock(return_value=(0, 0))), \
             patch("promotions.get_active", AsyncMock(return_value=None)), \
             patch("gift_campaign.card_line", AsyncMock(return_value="")), \
             patch("bot_discount.reminder", AsyncMock(return_value="")), \
             patch("bot_discount.display_price", AsyncMock(return_value=None)), \
             patch.object(product_card, "detail_keyboard", AsyncMock(return_value="KB")):
            return await restock_notify._send_card(bot, 11, product(quantity=4), "uz")

    async def test_card_leads_with_the_good_news(self):
        bot = AsyncMock()
        self.assertTrue(await self.send(bot))
        kwargs = bot.send_photo.await_args.kwargs
        self.assertTrue(kwargs["caption"].startswith("🎉 <b>Siz qiziqqan mahsulot do'konimizga qaytdi!</b>"))
        self.assertIn("50 000", kwargs["caption"])
        self.assertEqual(kwargs["reply_markup"], "KB")

    async def test_long_card_goes_as_photo_plus_text(self):
        # Over Telegram's 1024-character caption: photo first, then the whole
        # text with the buttons — never a refused send_photo.
        bot = AsyncMock()
        with patch("gamification.buyer_rate", AsyncMock(return_value=None)), \
             patch.object(product_card, "get_product_rating", AsyncMock(return_value=(0, 0))), \
             patch("promotions.get_active", AsyncMock(return_value=None)), \
             patch("gift_campaign.card_line", AsyncMock(return_value="")), \
             patch("bot_discount.reminder", AsyncMock(return_value="")), \
             patch("bot_discount.display_price", AsyncMock(return_value=None)), \
             patch.object(product_card, "detail_keyboard", AsyncMock(return_value="KB")):
            ok = await restock_notify._send_card(bot, 11, product(quantity=4, description="Uzun. " * 300), "uz")
        self.assertTrue(ok)
        self.assertIsNone(bot.send_photo.await_args.kwargs["caption"])
        text = bot.send_message.await_args.args[1]
        self.assertTrue(text.startswith("🎉 <b>Siz qiziqqan mahsulot do'konimizga qaytdi!</b>"))
        self.assertEqual(bot.send_message.await_args.kwargs["reply_markup"], "KB")

    async def test_blocked_buyer_is_not_an_error(self):
        bot = AsyncMock()
        bot.send_photo.side_effect = TelegramForbiddenError(method=None, message="bot was blocked")
        self.assertFalse(await self.send(bot))


class BotButtonTest(unittest.IsolatedAsyncioTestCase):
    async def keyboard(self, waiting, shelf=0):
        with patch.object(product_card, "get_cart_line_for_product", AsyncMock(return_value=(None, 0))), \
             patch.object(product_card, "get_cart_badge", AsyncMock(return_value=(0, 0))), \
             patch.object(database, "get_product", AsyncMock(return_value=product(quantity=shelf))), \
             patch.object(database, "is_waiting_restock", AsyncMock(return_value=waiting)):
            return await product_card.detail_keyboard(7, 5, "seeds", 2, "uz", True)

    async def test_sold_out_card_offers_the_bell(self):
        first = (await self.keyboard(False)).inline_keyboard[0][0]
        self.assertEqual(first.text, get_text("btn_restock_wait", "uz"))
        self.assertEqual(first.callback_data, "restock_wait:5:seeds:2")
        first = (await self.keyboard(True)).inline_keyboard[0][0]
        self.assertEqual(first.text, get_text("btn_restock_waiting", "uz"))

    async def test_held_in_other_carts_is_band_with_its_own_bell(self):
        # Savat broni: 3 on the shelf, all in other buyers' carts — "band", not
        # sold out, and the buyer may wait for it (owner, 2026-10-16).
        first = (await self.keyboard(False, shelf=3)).inline_keyboard[0][0]
        self.assertEqual(first.text, get_text("btn_held_wait", "uz"))
        self.assertEqual(first.callback_data, "restock_wait:5:seeds:2")
        first = (await self.keyboard(True, shelf=3)).inline_keyboard[0][0]
        self.assertEqual(first.text, get_text("btn_held_waiting", "uz"))

    async def test_tapping_the_bell(self):
        callback = MagicMock()
        callback.data = "restock_wait:5:seeds:2"
        callback.from_user.id = 7
        callback.answer = AsyncMock()
        callback.message.edit_reply_markup = AsyncMock()
        with patch.object(database, "get_user_language", AsyncMock(return_value="ru")), \
             patch.object(database, "get_product", AsyncMock(return_value=product())), \
             patch.object(database, "add_restock_wait", AsyncMock(return_value=True)) as add, \
             patch.object(product_card, "detail_keyboard", AsyncMock(return_value="KB")) as kb:
            await restock_notify.restock_wait_button(callback)
        add.assert_awaited_once_with(7, 5, "ru", "bot")
        callback.answer.assert_awaited_once_with(get_text("restock_wait_added", "ru"), show_alert=True)
        self.assertEqual(kb.await_args.args[:6], (7, 5, "seeds", 2, "ru", True))
        callback.message.edit_reply_markup.assert_awaited_once_with(reply_markup="KB")


class EndpointTest(unittest.IsolatedAsyncioTestCase):
    class Request(dict):
        def __init__(self, body):
            super().__init__({"user_id": 7, "user_lang": "uz_cyr"})
            self._body = body

        async def json(self):
            if isinstance(self._body, Exception):
                raise self._body
            return self._body

    async def test_site_button(self):
        with patch.object(database, "get_product", AsyncMock(return_value=product())), \
             patch.object(database, "add_restock_wait", AsyncMock(return_value=True)) as add:
            resp = await webapp_server.api_restock_wait(self.Request({"product_id": 5}))
        self.assertEqual(resp.status, 200)
        self.assertIn(b'"added"', resp.body)
        add.assert_awaited_once_with(7, 5, "uz_cyr", "site")

    async def test_bad_or_unknown(self):
        resp = await webapp_server.api_restock_wait(self.Request(ValueError("bad json")))
        self.assertEqual(resp.status, 400)
        with patch.object(database, "get_product", AsyncMock(return_value=None)):
            resp = await webapp_server.api_restock_wait(self.Request({"product_id": 99}))
        self.assertEqual(resp.status, 404)

    def test_route_is_registered(self):
        app = webapp_server.create_webapp(object())  # type: ignore[arg-type]
        routes = {(r.method, r.resource.canonical) for r in app.router.routes()}
        self.assertIn(("POST", "/api/restock-wait"), routes)


class OmborTest(unittest.TestCase):
    def test_waiting_buyers_shown_next_to_sold_out(self):
        products = [{"id": 5, "name": "Chia", "quantity": 0, "unit": "piece", "low_stock_threshold": None},
                    {"id": 6, "name": "Zigir", "quantity": 0, "unit": "piece", "low_stock_threshold": None},
                    {"id": 7, "name": "Bodom", "quantity": 2, "unit": "piece", "low_stock_threshold": None}]
        text = stock_alerts.summary_text(products, {5: 3, 7: 1})
        self.assertIn("• Chia — 🔔 <b>3 kishi kutyapti</b>", text)
        self.assertIn("• Zigir\n", text)
        self.assertNotIn("Bodom — 🔔", text)
        self.assertNotIn("kutyapti", stock_alerts.summary_text(products))


if __name__ == "__main__":
    unittest.main()
