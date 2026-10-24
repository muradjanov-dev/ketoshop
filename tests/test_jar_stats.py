"""🫙 Banka mahsulotlari 15 / 30 kun — to every admin once, /banka any time
(owner, 2026-10-24). No Telegram and no database."""
import asyncio
import os
import unittest
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import jar_stats as js


def run(coro):
    return asyncio.run(coro)


def row(name, qty, revenue, kind="product", b2b=0, unit="piece"):
    return {"kind": kind, "name": name, "qty": qty, "revenue": revenue, "b2b_qty": b2b, "unit": unit}


ROWS = [
    row("Bodom uni 1000gr", 51, 8_190_000),                      # not a jar
    row("Tabiiy GHEE 1000ml", 11, 1_281_000),
    row("Lasos baliq tushonkasi 700ml", 21, 1_717_500),
    row("Xandonpista pastasi 200gr", 12, 1_148_500, b2b=4),
    row("Keto <set>", 1, 250_000, kind="set"),                   # sets aren't jars
    row("Zaytun yog'i 1000ml", 0, 0),                            # nothing sold
]
PERIOD = {"start": "2026-10-10", "end": "2026-10-24"}


class ReportTest(unittest.TestCase):
    def test_jars_only_most_money_first(self):
        text = js.report_text(15, PERIOD, ROWS)
        self.assertTrue(text.startswith("🫙 <b>Banka mahsulotlari — oxirgi 15 kun (10.10–24.10)</b>"))
        self.assertLess(text.index("Lasos"), text.index("GHEE"))
        self.assertLess(text.index("GHEE"), text.index("Xandonpista"))
        self.assertNotIn("Bodom", text)
        self.assertNotIn("Keto", text)
        self.assertNotIn("Zaytun", text)
        self.assertIn("21 ta × ~81 786 = <b>1 717 500</b> so'm · pochta 1 dona: 21 000", text)
        self.assertIn("12 ta (shundan B2B 4)", text)
        self.assertIn("<b>Jami: 44 ta · 4 147 000 so'm</b>", text)

    def test_escaping_and_empty(self):
        text = js.report_text(30, PERIOD, [row("Asal <Zomin> & co 700 gr", 1, 100_000)])
        self.assertIn("Asal &lt;Zomin&gt; &amp; co 700 gr", text)
        self.assertIn("sotilmagan", js.report_text(30, PERIOD, ROWS[:1]))

    def test_fits_one_telegram_message(self):
        many = [row(f"Zaytun yog'i navi {i} — juda uzun nom bilan 1000ml", 3, 900_000 - i) for i in range(80)]
        text = js.report_text(30, PERIOD, many)
        self.assertLessEqual(len(text), 4096)
        self.assertIn("… va yana", text)
        self.assertIn("Jami: 240 ta", text)          # the total still counts every row

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


if __name__ == "__main__":
    unittest.main()
