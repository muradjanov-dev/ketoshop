"""All-product 15 / 30 day bot reports. No Telegram and no database."""
import asyncio
import os
import unittest
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import jar_stats as js
import keyboards


def run(coro):
    return asyncio.run(coro)


def row(name, qty, revenue, kind="product", b2b=0, unit="piece"):
    return {"kind": kind, "name": name, "qty": qty, "revenue": revenue, "b2b_qty": b2b, "unit": unit}


ROWS = [
    row("Bodom uni 1000gr", 51, 8_190_000),
    row("Tabiiy GHEE 1000ml", 11, 1_281_000),
    row("Lasos baliq tushonkasi 700ml", 21, 1_717_500),
    row("Xandonpista pastasi 200gr", 12, 1_148_500, b2b=4),
    row("Keto <set>", 1, 250_000, kind="set"),
    row("Zaytun yog'i 1000ml", 0, 0),                            # nothing sold
]
PERIOD = {"start": "2026-10-10", "end": "2026-10-24"}


class ReportTest(unittest.TestCase):
    def test_all_sold_products_and_sets_most_money_first(self):
        text = js.report_text(15, PERIOD, ROWS)
        self.assertTrue(text.startswith("📦 <b>Barcha mahsulotlar — oxirgi 15 kun (10.10–24.10)</b>"))
        self.assertLess(text.index("Bodom"), text.index("Lasos"))
        self.assertLess(text.index("Lasos"), text.index("GHEE"))
        self.assertLess(text.index("GHEE"), text.index("Xandonpista"))
        self.assertIn("Keto &lt;set&gt;</b> (to'plam)", text)
        self.assertNotIn("Zaytun", text)
        self.assertIn("Soni: 21 × ~81 786 = <b>1 717 500</b> so'm", text)
        self.assertIn("Soni: 12 (shundan B2B 4)", text)
        self.assertIn("<b>Jami: 5 xil · 12 587 000 so'm</b>", text)
        self.assertIn("bekor qilinganlar va sovg'alar kirmaydi", text)

    def test_historical_sales_show_goods_revenue_without_postal_quotes(self):
        sales = [row("Qora sedana 200gr", 0.6, 10_260),
                 row("GHEE 1000ml to'plami", 1, 100_000, kind="set")]
        for days in (15, 30):
            with self.subTest(days=days):
                text = "\n".join(js.report_messages(days, PERIOD, sales))
                self.assertIn("Soni: 0,6 × ~17 100 = <b>10 260</b> so'm", text)
                self.assertIn("<b>Jami: 2 xil · 110 260 so'm</b>", text)
                self.assertNotIn("pochta", text.lower())
                self.assertNotIn("UzPost", text)
                self.assertNotIn("18 000", text)

    def test_actual_postage_is_shown_once_per_order_separate_from_goods(self):
        sales = [row("Qora sedana 200gr", 0.6, 10_260), row("Zig'ir uni 300gr", 1, 16_000)]
        postage = [
            {"id": 1, "created_at": datetime(2026, 10, 24, 12, 0), "method": "uzpost", "fee": 15_000},
            {"id": 2, "created_at": datetime(2026, 10, 24, 14, 0), "method": "uzpost", "fee": 18_000},
        ]
        with patch.object(js.database, "get_product_sales", AsyncMock(return_value={"rows": sales, "postage_orders": postage})):
            texts = run(js.build_reports())
        text = "\n".join(t for t in texts if "oxirgi 30 kun" in t)
        self.assertIn("Jami: 2 xil · 26 260 so'm", text)
        self.assertIn("#1 · 24.10.2026 17:00 · UzPost: <b>15 000</b> so'm", text)
        self.assertIn("#2 · 24.10.2026 19:00 · UzPost: <b>18 000</b> so'm", text)
        self.assertEqual(text.count("#1 ·"), 1)
        self.assertEqual(text.count("#2 ·"), 1)
        self.assertIn("Pochta jami: 2 ta buyurtma · 33 000 so'm", text)
        self.assertNotIn("pochta 1 dona", text)

    def test_escaping_and_empty(self):
        text = js.report_text(30, PERIOD, [row("Asal <Zomin> & co 700 gr", 1, 100_000)])
        self.assertIn("Asal &lt;Zomin&gt; &amp; co 700 gr", text)
        self.assertIn("sotilmagan", js.report_text(30, PERIOD, ROWS[-1:]))
        self.assertNotIn("sotilmagan", js.report_text(30, PERIOD, ROWS[:1]))

    def test_long_report_keeps_every_product_in_valid_sized_messages(self):
        many = [row(f"Zaytun yog'i navi {i} — juda uzun nom bilan 1000ml", 3, 900_000 - i) for i in range(80)]
        messages = js.report_messages(30, PERIOD, many)
        self.assertGreater(len(messages), 1)
        text = "\n".join(messages)
        for message in messages:
            self.assertLessEqual(js._text_len(message), 4000)
            self.assertEqual(message.count("<b>"), message.count("</b>"))
            self.assertEqual(message.count("<i>"), message.count("</i>"))
            self.assertTrue(message.startswith("📦 <b>Barcha mahsulotlar — oxirgi 30 kun"))
        for product in many:
            self.assertEqual(text.count(f"<b>{product['name']}</b>"), 1)
        self.assertNotIn("… va yana", text)
        self.assertEqual(text.count("<b>Jami:"), 1)
        self.assertIn("Jami: 80 xil · 71 996 840 so'm", messages[-1])

    def test_oversized_name_with_html_and_emoji_is_split_safely(self):
        from html.parser import HTMLParser
        name = "🌰<&>" * 1500
        messages = js.report_messages(15, PERIOD, [row(name, 1, 100_000)])
        plain = []
        class TextParser(HTMLParser):
            def handle_data(self, data):
                plain.append(data)
        for message in messages:
            self.assertLessEqual(js._text_len(message), 4000)
            TextParser().feed(message.split("\n\n", 1)[1])
        self.assertIn(name, "".join(plain))
        self.assertIn("Jami: 1 xil", messages[-1])

    def test_gift_only_rows_are_not_sales(self):
        gift = dict(row("Sovg'a", 0, 0), gift_qty=5)
        messages = js.report_messages(15, PERIOD, [gift])
        self.assertEqual(len(messages), 1)
        self.assertIn("Bu davrda mahsulotlar sotilmagan.", messages[0])

    def test_product_with_blank_lines_keeps_its_html_together(self):
        name = "Bodom\n\nuni & <tabiiy>"
        messages = js.report_messages(15, PERIOD, [row(name, 2, 100_000)])
        self.assertEqual(len(messages), 1)
        self.assertIn("<b>Bodom\n\nuni &amp; &lt;tabiiy&gt;</b>", messages[0])

    def test_window(self):
        self.assertEqual(js.window(15, date(2026, 10, 24)), {"start": "2026-10-10", "end": "2026-10-24"})
        self.assertEqual(js.window(30, date(2026, 10, 24)), {"start": "2026-09-25", "end": "2026-10-24"})


class PushTest(unittest.TestCase):
    def _bot(self):
        bot = MagicMock()
        bot.send_message = AsyncMock()
        return bot

    def test_sends_both_periods_to_every_admin_once(self):
        bot = self._bot()
        sales = AsyncMock(return_value={"rows": ROWS})
        with patch.object(js, "_now_tk", return_value=datetime(2026, 10, 24, 18, 0)), \
                patch.object(js.database, "claim_release_notes", AsyncMock(return_value=True)), \
                patch.object(js.database, "get_product_sales", sales), \
                patch.object(js, "ADMIN_IDS", [1, 2, 1]), \
                patch.object(js.asyncio, "sleep", AsyncMock()):
            self.assertTrue(run(js.push_once(bot)))
        self.assertEqual([c.args[0] for c in bot.send_message.await_args_list], [1, 1, 2, 2])
        self.assertIn("oxirgi 15 kun", bot.send_message.await_args_list[0].args[1])
        self.assertIn("oxirgi 30 kun", bot.send_message.await_args_list[1].args[1])
        self.assertEqual(sales.await_args_list[1].args[0]["end"], "2026-10-24")

    def test_night_and_already_sent(self):
        bot = self._bot()
        claim = AsyncMock(return_value=False)
        with patch.object(js, "_now_tk", return_value=datetime(2026, 10, 24, 22, 30)), \
                patch.object(js.database, "claim_release_notes", claim):
            self.assertFalse(run(js.push_once(bot)))
        claim.assert_not_awaited()
        with patch.object(js, "_now_tk", return_value=datetime(2026, 10, 25, 9, 5)), \
                patch.object(js.database, "claim_release_notes", claim):
            self.assertTrue(run(js.push_once(bot)))
        bot.send_message.assert_not_awaited()

    def test_failed_build_gives_the_key_back(self):
        release = AsyncMock()
        with patch.object(js, "_now_tk", return_value=datetime(2026, 10, 24, 18, 0)), \
                patch.object(js.database, "claim_release_notes", AsyncMock(return_value=True)), \
                patch.object(js.database, "release_release_notes", release), \
                patch.object(js.database, "get_product_sales", AsyncMock(side_effect=RuntimeError)):
            with self.assertRaises(RuntimeError):
                run(js.push_once(self._bot()))
        release.assert_awaited_once_with(js.PUSH_KEY)


class CommandTest(unittest.TestCase):
    def _message(self, uid):
        msg = MagicMock()
        msg.from_user.id = uid
        msg.answer = AsyncMock()
        return msg

    def test_admins_only(self):
        with patch.object(js, "ADMIN_IDS", [7]), \
                patch.object(js.database, "get_product_sales", AsyncMock(return_value={"rows": ROWS})):
            stranger = self._message(99)
            run(js.cmd_banka(stranger))
            stranger.answer.assert_not_awaited()
            admin = self._message(7)
            run(js.cmd_banka(admin))
        self.assertEqual(admin.answer.await_count, 2)
        self.assertIn("Bodom", admin.answer.await_args_list[0].args[0])

    def test_admin_menu_exposes_command_and_button(self):
        self.assertIn("mahsulot_savdosi", [c.command for c in keyboards.ADMIN_COMMANDS])
        buttons = [button for row in keyboards.admin_stats_menu_keyboard("uz").inline_keyboard for button in row]
        self.assertIn("admin:product_sales", [b.callback_data for b in buttons])

    def test_callback_is_admin_only_and_answers_with_both_periods(self):
        with patch.object(js, "ADMIN_IDS", [7]), \
                patch.object(js.database, "get_product_sales", AsyncMock(return_value={"rows": ROWS})):
            callback = MagicMock()
            callback.answer = AsyncMock()
            callback.message = self._message(99)
            callback.from_user.id = 99
            run(js.show_product_sales(callback))
            callback.message.answer.assert_not_awaited()
            callback.from_user.id = 7
            run(js.show_product_sales(callback))
            self.assertEqual(callback.message.answer.await_count, 2)

    def test_build_error_returns_retry_message(self):
        with patch.object(js, "ADMIN_IDS", [7]), \
                patch.object(js, "build_reports", AsyncMock(side_effect=RuntimeError)), \
                self.assertLogs(js.logger, level="ERROR"):
            message = self._message(7)
            run(js.cmd_banka(message))
        self.assertIn("qayta urinib", message.answer.await_args.args[0])

    def test_command_sends_all_chunks_of_both_periods(self):
        many = [row(f"Bodom uni navi {i}", 1, 100_000) for i in range(100)]
        with patch.object(js, "ADMIN_IDS", [7]), \
                patch.object(js.database, "get_product_sales", AsyncMock(return_value={"rows": many})):
            message = self._message(7)
            run(js.cmd_banka(message))
        texts = [call.args[0] for call in message.answer.await_args_list]
        self.assertGreater(len(texts), 2)
        for days in (15, 30):
            period_messages = [text for text in texts if f"oxirgi {days} kun" in text]
            self.assertEqual("\n".join(period_messages).count("Jami: 100 xil"), 1)
            for product in many:
                self.assertEqual("\n".join(period_messages).count(f"<b>{product['name']}</b>"), 1)


if __name__ == "__main__":
    unittest.main()
