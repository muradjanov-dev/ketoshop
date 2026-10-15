"""Admin-uploaded product images and complete descriptions, without real sends."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.methods import SendMessage, SendPhoto
from aiogram.types import CallbackQuery, Message

import product_card
import product_of_day
import webapp_server
from handlers import catalog, seller
from tg_safety import strip_markup
from translit import lat_to_cyr


def product(**changes):
    return dict({"id": 145, "name": "Bodom uni po‘stlog‘i bilan", "name_ru": "Миндальная мука",
                 "description": "To‘liq tavsif. " * 100 + "TAVSIF OXIRI",
                 "description_ru": "Полное описание. " * 100 + "КОНЕЦ ОПИСАНИЯ",
                 "price": 150000., "quantity": 3., "unit": "kg", "category": "un",
                 "discount_percent": 10, "discount_until": None, "is_active": 1,
                 "photo_id": None, "image_url": "/img/3"}, **changes)


class RecordingSession(BaseSession):
    """Telegram boundary: reject oversized payloads just as the API does."""
    def __init__(self):
        super().__init__()
        self.requests = []
        self.reject_photo = False
        self.text_retries = 0

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        raise AssertionError("No network downloads in tests")
        yield

    async def make_request(self, bot, method, timeout=None):
        self.requests.append(method)
        if isinstance(method, SendMessage) and self.text_retries:
            self.text_retries -= 1
            raise TelegramRetryAfter(method=method, message="Too Many Requests", retry_after=1)
        if isinstance(method, SendPhoto) and self.reject_photo:
            raise TelegramBadRequest(method=method, message="wrong file identifier/HTTP URL specified")
        field, limit = ("caption", 1024) if isinstance(method, SendPhoto) else ("text", 4096)
        text = getattr(method, field, None) or ""
        visible = strip_markup(text) if getattr(method, "parse_mode", None) == "HTML" else text
        if len(visible.encode("utf-16-le")) // 2 > limit:
            raise TelegramBadRequest(method=method, message="message is too long")
        if method.__api_method__ in ("deleteMessage", "answerCallbackQuery"):
            return True
        return Message.model_validate({"message_id": len(self.requests), "date": 0,
                                       "chat": {"id": 7, "type": "private"}}, context={"bot": bot})


class ProductMediaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session = RecordingSession()
        self.bot = Bot("1:test", session=self.session)
        for p in (
            patch.object(product_card, "get_product_rating", AsyncMock(return_value=(0, 0))),
            patch.object(product_card, "get_cart_line_for_product", AsyncMock(return_value=(None, 0))),
            patch.object(product_card, "get_cart_badge", AsyncMock(return_value=(0, 0))),
            patch("database.apply_holds", AsyncMock(side_effect=lambda rows, *args: rows)),
            patch("bot_discount.display_price", AsyncMock(return_value=None)),
            patch("bot_discount.reminder", AsyncMock(return_value="🎁 Bot orqali buyurtmaga 10% chegirma!")),
            patch("gift_campaign.card_line", AsyncMock(return_value="🎁 Har buyurtmaga sovg‘a!")),
            patch("promotions.get_active", AsyncMock(return_value=None)),
            patch("gamification.buyer_rate", AsyncMock(return_value=.005)),
            patch("gamification.is_enabled", AsyncMock(return_value=False)),
            patch.object(product_card, "WEBAPP_URL", "https://keto.example", create=True),
            patch.object(catalog, "get_user_language", AsyncMock(return_value="uz")),
            patch.object(catalog, "add_product_view", AsyncMock()),
            patch("product_tips.tip_for", AsyncMock(return_value="Bir chimdim ksantan bilan pishiring ✨")),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.addAsyncCleanup(self.bot.session.close)

    def sent(self):
        return [m for m in self.session.requests if isinstance(m, (SendPhoto, SendMessage))]

    async def send(self, p):
        await product_card.send_card(self.bot, 7, p, "uz", rate=.005)
        return self.sent()

    async def test_existing_web_upload_is_sent_with_complete_description_and_buttons(self):
        p = product()
        messages = await self.send(p)
        self.assertIsInstance(messages[0], SendPhoto)
        self.assertEqual(messages[0].photo, "https://keto.example/img/3")
        self.assertIsNone(messages[0].reply_markup)
        self.assertIn(p["description"], strip_markup(messages[-1].text))
        self.assertIn("135 000", strip_markup(messages[-1].text))
        callbacks = [b.callback_data for row in messages[-1].reply_markup.inline_keyboard for b in row]
        self.assertIn("detail_inc:145::0", callbacks)

    async def test_telegram_photo_and_short_description_stay_in_one_card(self):
        messages = await self.send(product(description="Qisqa tavsif", image_url=None, photo_id="AgACphoto"))
        self.assertEqual(len(messages), 1)
        self.assertIsInstance(messages[0], SendPhoto)
        self.assertEqual(messages[0].photo, "AgACphoto")
        self.assertIn("Qisqa tavsif", messages[0].caption)
        self.assertIsNotNone(messages[0].reply_markup)

    async def test_web_replacement_wins_over_legacy_telegram_photo(self):
        messages = await self.send(product(description="Qisqa", photo_id="old-photo"))
        self.assertEqual(messages[0].photo, "https://keto.example/img/3")

    async def test_absolute_web_image_is_sent_as_is(self):
        messages = await self.send(product(description="Qisqa", image_url="https://cdn.example/bodom.jpg"))
        self.assertEqual(messages[0].photo, "https://cdn.example/bodom.jpg")

    async def test_no_image_still_shows_whole_description(self):
        p = product(image_url=None)
        messages = await self.send(p)
        self.assertEqual(len(messages), 1)
        self.assertIsInstance(messages[0], SendMessage)
        self.assertIn(p["description"], strip_markup(messages[0].text))

    async def test_broken_image_does_not_hide_description_or_order_buttons(self):
        self.session.reject_photo = True
        p = product()
        messages = await self.send(p)
        self.assertIsInstance(messages[-1], SendMessage)
        self.assertIn(p["description"], strip_markup(messages[-1].text))
        self.assertIsNotNone(messages[-1].reply_markup)

    async def test_catalog_open_uses_web_image_and_whole_description(self):
        p = product()
        callback = CallbackQuery.model_validate({
            "id": "test", "chat_instance": "test", "from": {"id": 7, "is_bot": False, "first_name": "Test"},
            "message": {"message_id": 42, "date": 0, "chat": {"id": 7, "type": "private"}, "text": "Catalog"},
            "data": "product:145:un:0",
        }, context={"bot": self.bot})
        with patch.object(catalog, "_product_for", AsyncMock(return_value=p)):
            await catalog._render_product_detail(callback, 145, "un", 0, track_view=True)
        messages = self.sent()
        self.assertEqual(messages[0].photo, "https://keto.example/img/3")
        self.assertIn(p["description"], strip_markup(messages[-1].text))
        self.assertIn("ksantan", messages[-1].text)
        callbacks = [b.callback_data for row in messages[-1].reply_markup.inline_keyboard for b in row]
        self.assertIn("detail_inc:145:un:0", callbacks)

    async def test_channel_uses_same_image_and_keeps_full_description(self):
        p = product()
        self.assertTrue(await product_of_day.post_to_channel(self.bot, p))
        messages = self.sent()
        self.assertEqual(messages[0].photo, "https://keto.example/img/3")
        self.assertIn(lat_to_cyr(p["description"]), strip_markup(messages[-1].text))
        self.assertTrue(messages[-1].reply_markup.inline_keyboard[0][0].url.endswith("prod_145"))

    async def test_cached_broadcast_caption_is_complete_in_each_language(self):
        p = product()
        cache = product_card.CaptionCache(p)
        for lang, desc in (("uz", p["description"]), ("ru", p["description_ru"]),
                           ("uz_cyr", lat_to_cyr(p["description"]))):
            caption = await cache.get(lang, .005)
            self.assertIn(desc, strip_markup(caption))

    async def test_emoji_caption_limit_is_measured_in_utf16(self):
        p = product(description="🌰" * 450 + "TAMOM")
        messages = await self.send(p)
        self.assertIsInstance(messages[-1], SendMessage)
        self.assertIn(p["description"], strip_markup(messages[-1].text))

    async def test_very_long_card_preserves_every_character_across_text_messages(self):
        p = product(description="🌰" * 2000 + "TAMOM")
        messages = await self.send(p)
        text_messages = [m for m in messages if isinstance(m, SendMessage)]
        combined = "".join(strip_markup(m.text) if m.parse_mode == "HTML" else m.text for m in text_messages)
        self.assertIn(p["description"], combined)
        self.assertIsNotNone(text_messages[-1].reply_markup)
        self.assertTrue(all(m.reply_markup is None for m in text_messages[:-1]))

    async def test_product_text_with_angle_brackets_and_ampersands_is_not_lost(self):
        p = product(description="Tarkibi <bodom> & un; < 5 g", name="Bodom & <un>")
        messages = await self.send(p)
        visible = strip_markup(messages[0].caption)
        self.assertIn(p["description"], visible)
        self.assertIn(p["name"], visible)

    async def test_mini_app_also_shows_admin_uploaded_product_image(self):
        p = product(photo_id="old-photo")
        result = webapp_server._serialize_product(p, "uz")
        self.assertEqual(result["photo_url"], "/img/3")
        self.assertEqual(result["description"], p["description"])

    async def test_bot_photo_replacement_clears_previous_web_image(self):
        state = SimpleNamespace(get_data=AsyncMock(return_value={"edit_product_id": 145, "lang": "uz"}), clear=AsyncMock())
        message = SimpleNamespace(photo=[SimpleNamespace(file_id="new-photo")], from_user=SimpleNamespace(id=7))
        with patch.object(seller, "update_product", AsyncMock()) as update, \
             patch.object(seller, "send_my_products_after_edit", AsyncMock()):
            await seller.process_edit_photo(message, state)
        self.assertEqual(update.await_args.args, (145,))
        self.assertEqual(update.await_args.kwargs, {"photo_id": "new-photo", "image_url": None})

    async def test_document_photo_replacement_also_clears_previous_web_image(self):
        state = SimpleNamespace(get_data=AsyncMock(return_value={"edit_product_id": 145, "lang": "uz"}), clear=AsyncMock())
        message = SimpleNamespace(from_user=SimpleNamespace(id=7))
        with patch.object(seller, "_doc_to_photo_id", AsyncMock(return_value="new-photo")), \
             patch.object(seller, "update_product", AsyncMock()) as update, \
             patch.object(seller, "send_my_products_after_edit", AsyncMock()):
            await seller.process_edit_photo_as_doc(message, state, self.bot)
        self.assertEqual(update.await_args.kwargs, {"photo_id": "new-photo", "image_url": None})

    async def test_seller_preview_shows_web_image_and_whole_description(self):
        p = product()
        callback = CallbackQuery.model_validate({
            "id": "test", "chat_instance": "test", "from": {"id": 7, "is_bot": False, "first_name": "Test"},
            "message": {"message_id": 42, "date": 0, "chat": {"id": 7, "type": "private"}, "text": "Products"},
            "data": "view_prod:145:0",
        }, context={"bot": self.bot})
        with patch.object(seller, "get_product", AsyncMock(return_value=p)), \
             patch.object(seller, "get_user_language", AsyncMock(return_value="uz")):
            await seller.view_product(callback)
        messages = self.sent()
        self.assertIsInstance(messages[0], SendPhoto)
        self.assertEqual(messages[0].photo, "https://keto.example/img/3")
        self.assertIn(p["description"], strip_markup(messages[-1].text))

    async def test_spotlight_admin_notifications_still_arrive(self):
        with patch.object(product_of_day, "ADMIN_IDS", [7]):
            await product_of_day._notify_admins(self.bot, "<b>Spotlight status</b>")
        self.assertEqual([m.text for m in self.sent()], ["<b>Spotlight status</b>"])

    async def test_spotlight_rate_limit_retries_only_the_unsent_text(self):
        self.session.text_retries = 1
        p = product()
        with patch("asyncio.sleep", AsyncMock()):
            ok = await product_of_day._send_to_user(self.bot, 7, p, "uz", product_card.CaptionCache(p))
        self.assertTrue(ok)
        self.assertEqual(sum(isinstance(m, SendPhoto) for m in self.sent()), 1)
        self.assertEqual(sum(isinstance(m, SendMessage) for m in self.sent()), 2)

    async def test_exhausted_rate_limit_does_not_replay_delivered_photo(self):
        self.session.text_retries = 2
        p = product()
        with patch("asyncio.sleep", AsyncMock()):
            ok = await product_of_day._send_to_user(self.bot, 7, p, "uz", product_card.CaptionCache(p))
        self.assertFalse(ok)
        self.assertEqual(sum(isinstance(m, SendPhoto) for m in self.sent()), 1)
        self.assertEqual(sum(isinstance(m, SendMessage) for m in self.sent()), 2)

    async def test_caption_boundary_counts_emoji_after_html_parsing(self):
        for ending, want_count in (("🌰🌰", 1), ("🌰🌰x", 2)):
            with self.subTest(ending=ending):
                self.session.requests.clear()
                text = "<b>" + "a" * 1020 + ending + "</b>"
                await product_card.send_product_message(self.bot, 7, product(), text, None)
                self.assertEqual(len(self.sent()), want_count)
                self.assertEqual(self.sent()[0].caption, text if want_count == 1 else None)

    async def test_message_boundary_counts_entities_after_html_parsing(self):
        for count, want_count in ((4096, 1), (4097, 2)):
            with self.subTest(count=count):
                self.session.requests.clear()
                await product_card.send_product_message(
                    self.bot, 7, product(image_url=None), "&amp;" * count, None)
                messages = self.sent()
                self.assertEqual(len(messages), want_count)
                visible = "".join(strip_markup(m.text) if m.parse_mode == "HTML" else m.text for m in messages)
                self.assertEqual(visible, "&" * count)


if __name__ == "__main__":
    unittest.main()
