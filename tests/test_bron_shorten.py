"""/bron: hozirgi bronlarni 1 soatga qisqartirish (egasi, 2026-10-17: "6-1
soatga tushir"). Qoida (RESERVE_HOURS) o'zgarmaydi. Bazaga ulanmasdan."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import cart_reservations as cr
import database


def run(coro):
    return asyncio.run(coro)


class ShortenTest(unittest.TestCase):
    def callback(self, data):
        cb = MagicMock()
        cb.data = data
        cb.answer = AsyncMock()
        cb.message.edit_text = AsyncMock()
        return cb

    def test_button_only_while_something_is_held(self):
        self.assertIsNone(cr.holds_keyboard([]))
        kb = cr.holds_keyboard([{"user_id": 1}])
        self.assertEqual(kb.inline_keyboard[0][0].callback_data, "bron:short")
        self.assertIn("1 soatga", kb.inline_keyboard[0][0].text)

    def test_asks_before_changing_anything(self):
        cb = self.callback("bron:short")
        with patch.object(database, "shorten_live_holds", AsyncMock()) as shorten:
            run(cr.on_shorten_ask(cb))
        shorten.assert_not_awaited()
        buttons = [b.callback_data for b in cb.message.edit_text.await_args.kwargs["reply_markup"].inline_keyboard[0]]
        self.assertEqual(buttons, ["bron:short:yes", "bron:short:no"])

    def test_yes_shortens_to_one_hour_and_keeps_the_rule(self):
        cb = self.callback("bron:short:yes")
        with patch.object(database, "shorten_live_holds", AsyncMock(return_value=4)) as shorten:
            run(cr.on_shorten(cb))
        shorten.assert_awaited_once_with(1)
        text = cb.message.edit_text.await_args.args[0]
        self.assertIn("4 ta savat qatorining broni 1 soatga", text)
        self.assertIn(f"yana {database.RESERVE_HOURS} soatga", text)

    def test_no_changes_nothing(self):
        cb = self.callback("bron:short:no")
        with patch.object(database, "shorten_live_holds", AsyncMock()) as shorten:
            run(cr.on_shorten(cb))
        shorten.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
