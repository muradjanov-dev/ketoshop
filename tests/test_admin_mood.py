"""Admin kayfiyat qatori: xabarga mos gap, faqat admin bildirishnomalariga."""
import asyncio
import os
import random
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

from aiogram.methods import SendMessage, SendPhoto

import admin_mood as m
import stock_alerts


def run_mw(method, current_user=None, admins=(10, 20)):
    sent = []

    async def make_request(bot, meth):
        sent.append(meth)
        return True

    async def go():
        m._lang_cache.update({a: (1e18, "uz") for a in admins})
        tok = m._current_user.set(current_user)
        try:
            await m.AdminCheerMiddleware(list(admins))(make_request, None, method)
        finally:
            m._current_user.reset(tok)
    asyncio.run(go())
    return sent[0]


class ClassifyTest(unittest.TestCase):
    def test_kinds(self):
        cases = {
            "🔔 <b>Yangi buyurtma #5</b>\n💵 To'lov: Naqd\n💰 Jami: 90 000 so'm": "new_order",
            "Buyurtma #5 yo'lga chiqdi": "shipped",
            "Buyurtma #5 yetkazildi": "delivered",
            "Mijoz buyurtma #5 ni bekor qildi": "cancel",
            "🧾 #5 buyurtma to'lov cheki": "cheque",
            "📊 Kunlik hisobot: 3 ta buyurtma": "report",
            "Маҳсулот тугади! 📦 Зиғир уни": "stock",
            "Новый заказ #9": "new_order",
            "Salom": "generic",
        }
        for text, kind in cases.items():
            self.assertEqual(m.classify(text), kind, text)

    def test_line_uses_message_facts(self):
        text = "🔔 <b>Yangi buyurtma #512</b>\n💰 <b>Jami: 184 000 so'm</b>"
        self.assertEqual(m.facts(text), {"order": "512", "amount": "184 000"})
        lines = {m.cheer_line("Buyurtma #512 yetkazildi", "uz", random.Random(i)) for i in range(40)}
        self.assertTrue(any("#512" in line for line in lines))
        for line in lines:
            self.assertNotIn("{", line)

    def test_product_name_is_escaped(self):
        f = m.facts("Tugadi\n📦 Choy <b>&</b> qahva")
        self.assertEqual(f["product"], "Choy &amp; qahva")


class MiddlewareTest(unittest.TestCase):
    def test_admin_notification_gets_line(self):
        out = run_mw(SendMessage(chat_id=10, text="Buyurtma #7 yetkazildi"))
        self.assertTrue(out.text.startswith("Buyurtma #7 yetkazildi\n\n"))
        self.assertGreater(len(out.text), len("Buyurtma #7 yetkazildi") + 5)

    def test_non_admin_untouched(self):
        out = run_mw(SendMessage(chat_id=99, text="Buyurtma #7 yetkazildi"))
        self.assertEqual(out.text, "Buyurtma #7 yetkazildi")

    def test_reply_to_own_action_untouched(self):
        out = run_mw(SendMessage(chat_id=10, text="Admin panel"), current_user=10)
        self.assertEqual(out.text, "Admin panel")

    def test_other_admin_during_update_gets_line(self):
        out = run_mw(SendMessage(chat_id=20, text="Buyurtma #7 bekor"), current_user=10)
        self.assertNotEqual(out.text, "Buyurtma #7 bekor")

    def test_quiet_and_limits(self):
        with m.quiet():
            out = run_mw(SendMessage(chat_id=10, text="x"))
        self.assertEqual(out.text, "x")
        long = "a" * 4090
        self.assertEqual(run_mw(SendMessage(chat_id=10, text=long)).text, long)
        cap = run_mw(SendPhoto(chat_id=10, photo="id", caption="🧾 #5 chek"))
        self.assertIn("\n\n", cap.caption)
        md = run_mw(SendMessage(chat_id=10, text="*x*", parse_mode="MarkdownV2"))
        self.assertEqual(md.text, "*x*")


class StockAlertTextTest(unittest.TestCase):
    def test_cyrillic_keeps_product_name(self):
        p = {"name": "Зиғир уни 300гр", "quantity": 0, "unit": "piece", "low_stock_threshold": None}
        t = stock_alerts._alert_text(p, "out", "uz_cyr")
        self.assertIn("«Зиғир уни 300гр»", t)
        self.assertIn("харидорлар", t)

    def test_low_keeps_facts(self):
        p = {"name": "Stevia", "quantity": 3, "unit": "piece", "low_stock_threshold": None}
        t = stock_alerts._alert_text(p, "low", "ru")
        self.assertIn("«Stevia»", t)
        self.assertIn("<b>3", t)
        self.assertIn("порог: 5", t)


if __name__ == "__main__":
    unittest.main()
