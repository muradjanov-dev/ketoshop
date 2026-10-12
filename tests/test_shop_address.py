"""«📍 Keto shop manzili» — kanal va botdagi post tagidagi havola.
Telegram va bazaga ulanmasdan; hech qanday xabar yuborilmaydi."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import shop_address

LANGS = ("uz", "uz_cyr", "ru")
URL = "https://t.me/ketoshop_uz/1071"


def run(coro):
    return asyncio.run(coro)


class LineTest(unittest.TestCase):
    def test_link_in_every_language(self):
        self.assertEqual(shop_address.line("uz"), f'📍 <a href="{URL}">Keto shop manzili</a>')
        self.assertEqual(shop_address.line("uz_cyr"), f'📍 <a href="{URL}">Кето шоп манзили</a>')
        self.assertEqual(shop_address.line("ru"), f'📍 <a href="{URL}">Адрес Keto shop</a>')

    def test_footer_is_its_own_paragraph(self):
        for lang in LANGS:
            self.assertEqual(shop_address.footer(lang), "\n\n" + shop_address.line(lang))

    def test_add_respects_the_limit(self):
        self.assertTrue(shop_address.add("Salom", "uz").endswith(shop_address.line("uz")))
        long = "x" * 1000
        self.assertEqual(shop_address.add(long, "uz", 1024), long)       # would not fit
        self.assertLessEqual(len(shop_address.add("x" * 900, "uz", 1024)), 1024)


class PostsTest(unittest.TestCase):
    """Har bir post yuboruvchi manzilni eng oxirgi qatorga qo'yadi."""

    def test_news_announcement(self):
        import news_announce
        for lang in LANGS:
            self.assertTrue(news_announce.text_for(lang).endswith(shop_address.line(lang)), lang)

    def test_monthly_report_in_the_channel_language(self):
        import monthly_report
        text = monthly_report.text()
        self.assertTrue(text.endswith(shop_address.line("uz_cyr")))
        self.assertLess(len(text), 4096)

    def test_onboarding_video_caption(self):
        import onboarding_video
        for lang in LANGS:
            caption = onboarding_video.caption(lang)
            self.assertTrue(caption.endswith(shop_address.line(lang)), lang)
            self.assertLessEqual(len(caption), 1024)

    def test_campaign_message_buyer_and_channel(self):
        import bot_discount_campaign as campaign
        for step in campaign.STEPS:
            for lang in LANGS:
                msgs = campaign._messages(step, lang, None)
                self.assertTrue(msgs[-1][0].endswith(shop_address.line(lang)), (step, lang))
            msgs = campaign._messages(step, "uz", None, channel=True)
            self.assertTrue(msgs[-1][0].endswith(shop_address.line("uz_cyr")), step)

    def test_campaign_price_list_only_on_the_last_part(self):
        import bot_discount_campaign as campaign
        items = [{"name": f"Mahsulot {i:03d} uzun nom bilan", "name_ru": None, "category": "flour",
                  "is_set": False, "base": 123000, "new": 110700} for i in range(150)]
        with patch.object(campaign, "get_category_name", lambda key, lang: "Un"):
            msgs = campaign._messages("left3", "ru", items)
        self.assertGreater(len(msgs), 1)
        self.assertTrue(all(URL not in text for text, _ in msgs[:-1]))
        self.assertTrue(msgs[-1][0].endswith(shop_address.line("ru")))
        self.assertIsNotNone(msgs[-1][1])                                # button stays with it
        self.assertTrue(all(len(text) <= 4096 for text, _ in msgs))


class SpotlightCardTest(unittest.TestCase):
    """Kun mahsuloti kartochkasi post sifatida manzil bilan; katalogda — yo'q."""

    PRODUCT = {"id": 7, "name": "Bodom uni", "name_ru": None, "description": "Tavsif " * 200,
               "description_ru": None, "price": 120000, "unit": "piece", "quantity": 10,
               "seller_name": "Ketoshop", "discount_percent": 0, "discount_until": None}

    def caption(self, **kw):
        import bot_discount
        import gift_campaign
        import product_card
        import promotions
        with patch.object(bot_discount, "reminder", AsyncMock(return_value="🎁 10%")), \
             patch.object(gift_campaign, "card_line", AsyncMock(return_value="")), \
             patch.object(promotions, "get_active", AsyncMock(return_value=None)), \
             patch.object(product_card, "get_product_rating", AsyncMock(return_value=(0, 0))):
            return run(product_card.build_caption(self.PRODUCT, "uz", None, "💡 G'oya", **kw))

    def test_post_card_ends_with_the_address(self):
        text = self.caption(address=True)
        self.assertTrue(text.endswith("\n\n" + shop_address.line("uz")))
        self.assertLessEqual(len(text), 1024)                           # long description trimmed

    def test_browsing_card_has_none(self):
        self.assertNotIn(URL, self.caption())


if __name__ == "__main__":
    unittest.main()
