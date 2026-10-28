"""Yangi alifbo (Ö Ğ Ş Ç, Law OʻRQ-1184) — owner, 2026-10-28: "loyihani yangi
alifboga o'tkaz", now, with a switch. No Telegram and no database."""
import asyncio
import json
import os
import pathlib
import shutil
import subprocess
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

from aiogram.client.session.middlewares.manager import RequestMiddlewareManager
from aiogram.methods import AnswerCallbackQuery, SendMessage, SendPhoto, SetMyCommands
from aiogram.types import (BotCommand, InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, MessageEntity, ReplyKeyboardMarkup)

import alphabet
from translit import lat_to_cyr, to_new_latin, to_old_latin

ROOT = pathlib.Path(__file__).resolve().parents[1]

CASES = {
    "O'zbekiston": "Özbekiston",
    "Sog' bo'ling! Tog' asali": "Soğ böling! Toğ asali",
    "Shokolad va choy": "Şokolad va çoy",
    "SHOSHILINCH": "ŞOŞILINÇ",
    "Kepakli bug‘doy uni, Zaytun yog‘i, o‘g‘il": "Kepakli buğdoy uni, Zaytun yoği, öğil",
    "Mahsulotlarimiz sizga ma'qul keldimi?": "Mahsulotlarimiz sizga ma'qul keldimi?",
    "mo''tadil, ta'm, san'at": "mö'tadil, ta'm, san'at",
    "Is'hoq as'hob": "Is\u200choq as\u200chob",
    "yangi, tong, ming": "yangi, tong, ming",
    "'Kakao' va 'Savat' tugmasi, bo'lsa 'Choy'": "'Kakao' va 'Savat' tugmasi, bölsa 'Çoy'",
    "<b>Bo'lim</b> /sharhlar @ketoshop_uz https://t.me/ketoshopbot?start=ig_shop":
        "<b>Bölim</b> /sharhlar @ketoshop_uz https://t.me/ketoshopbot?start=ig_shop",
    "Ketoshop'dan xarid · KETO shop · «Победа» Charged": "Ketoshop'dan xarid · KETO shop · «Победа» Charged",
    "{name}, so'm — iltimos, /skip bosing": "{name}, söm — iltimos, /skip bosing",
    "Шоколад ва чой": "Шоколад ва чой",
}


def run(coro):
    return asyncio.run(coro)


class ConvertTest(unittest.TestCase):
    def test_rules(self):
        for old, new in CASES.items():
            self.assertEqual(to_new_latin(old), new, old)
            self.assertEqual(to_new_latin(new), new, new)          # idempotent

    def test_back_to_old_and_cyrillic(self):
        self.assertEqual(to_old_latin("Şokolad Çoy Ğalla öz"), "Shokolad Choy G'alla o'z")
        self.assertEqual(lat_to_cyr("Şokolad öz ğalla çoy"), "Шоколад ўз ғалла чой")
        self.assertEqual(lat_to_cyr("Shokolad o'z g'alla choy"), "Шоколад ўз ғалла чой")

    def test_js_matches_python(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        html = (ROOT / "webapp" / "index.html").read_text(encoding="utf-8")
        start, end = html.index("const NEW_ALPHABET"), html.index("function _nlActive")
        js = html[start:end] + ("\nconst C = %s;\nprocess.stdout.write(JSON.stringify(C.map(toNewLatin)));"
                                % json.dumps(list(CASES), ensure_ascii=False))
        out = subprocess.run([node, "-e", js], capture_output=True, text=True, encoding="utf-8", check=True)
        self.assertEqual(json.loads(out.stdout), list(CASES.values()))
        admin = (ROOT / "webapp" / "admin.html").read_text(encoding="utf-8")
        self.assertIn(html[start:end], admin)                      # one converter, both pages


def _send(chat_id, text="Bo'lim: sharhlar", **kw):
    return SendMessage(chat_id=chat_id, text=text, **kw)


class MiddlewareTest(unittest.TestCase):
    def setUp(self):
        alphabet._langs.clear()
        alphabet._state["on"] = True

    def _through(self, method, langs=None):
        sent = []

        async def make_request(bot, m):
            sent.append(m)
            return True

        async def lang_of(uid):
            return (langs or {}).get(uid, "uz")

        with patch.object(alphabet.database, "get_user_language", side_effect=lang_of):
            run(alphabet.NewAlphabetMiddleware()(make_request, MagicMock(), method))
        return sent[0]

    def test_latin_reader_gets_text_and_buttons_converted(self):
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🛒 Savatga qo'shish",
                                                                          callback_data="add:shokolad")]])
        out = self._through(_send(5, reply_markup=kb))
        self.assertEqual(out.text, "Bölim: şarhlar")
        self.assertEqual(out.reply_markup.inline_keyboard[0][0].text, "🛒 Savatga qöşiş")
        self.assertEqual(out.reply_markup.inline_keyboard[0][0].callback_data, "add:shokolad")

    def test_reply_keyboard_and_captions(self):
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🏠 Bosh sahifa")]],
                                 input_field_placeholder="Mahsulot nomini yozing")
        out = self._through(SendPhoto(chat_id=5, photo="AgACshch", caption="Choy", reply_markup=kb))
        self.assertEqual(out.caption, "Çoy")
        self.assertEqual(out.photo, "AgACshch")                  # file ids are never touched
        self.assertEqual(out.reply_markup.keyboard[0][0].text, "🏠 Boş sahifa")

    def test_other_readers_and_groups(self):
        self.assertEqual(self._through(_send(6), {6: "ru"}).text, "Bo'lim: sharhlar")
        self.assertEqual(self._through(_send(7), {7: "uz_cyr"}).text, "Bo'lim: sharhlar")
        self.assertEqual(self._through(_send(-1004478720239)).text, "Bölim: şarhlar")
        self.assertEqual(self._through(_send("@ketoshop_uz")).text, "Bölim: şarhlar")

    def test_left_alone(self):
        ents = [MessageEntity(type="bold", offset=0, length=5)]
        self.assertEqual(self._through(_send(5, entities=ents)).text, "Bo'lim: sharhlar")
        alphabet._state["on"] = False
        self.assertEqual(self._through(_send(5)).text, "Bo'lim: sharhlar")
        alphabet._state["on"] = True
        with patch.dict(os.environ, {"NEW_ALPHABET": "0"}):
            self.assertEqual(self._through(_send(5)).text, "Bo'lim: sharhlar")

    def test_popup_follows_the_tapping_user(self):
        import admin_mood
        token = admin_mood._current_user.set(5)
        try:
            out = self._through(AnswerCallbackQuery(callback_query_id="1", text="Savatga qo'shildi",
                                                    show_alert=True))
        finally:
            admin_mood._current_user.reset(token)
        self.assertEqual(out.text, "Savatga qöşildi")

    def test_command_menu(self):
        cmds = [BotCommand(command="sharhlar", description="Sharhlar statistikasi")]
        uz = self._through(SetMyCommands(commands=cmds))
        self.assertEqual(uz.commands[0].command, "sharhlar")
        self.assertEqual(uz.commands[0].description, "Şarhlar statistikasi")
        ru = self._through(SetMyCommands(commands=cmds, language_code="ru"))
        self.assertEqual(ru.commands[0].description, "Sharhlar statistikasi")

    def test_runs_after_the_admin_cheer_line(self):
        import admin_mood
        manager = RequestMiddlewareManager()
        manager(admin_mood.AdminCheerMiddleware([5]))
        manager(alphabet.NewAlphabetMiddleware())
        sent = []

        async def make_request(bot, method, **kw):
            sent.append(method)

        with patch.object(admin_mood, "cheer_line", return_value="Choy damlab qo'ying"), \
                patch.object(admin_mood, "_admin_lang", AsyncMock(return_value="uz")), \
                patch.object(alphabet.database, "get_user_language", AsyncMock(return_value="uz")):
            run(manager.wrap_middlewares(make_request)(MagicMock(), _send(5, text="Yangi buyurtma")))
        self.assertTrue(sent[0].text.endswith("Çoy damlab qöying"), sent[0].text)


class SwitchTest(unittest.TestCase):
    def test_admins_only_and_it_flips(self):
        cb = MagicMock()
        cb.data = "alifbo:off"
        cb.from_user.id = 99
        cb.answer = AsyncMock()
        with patch.object(alphabet, "ADMIN_IDS", [7]), patch.object(alphabet, "set_on", AsyncMock()) as set_on:
            run(alphabet.toggle(cb))
            set_on.assert_not_awaited()
            cb.from_user.id = 7
            cb.message.edit_text = AsyncMock()
            run(alphabet.toggle(cb))
        set_on.assert_awaited_once_with(False)


class SearchTest(unittest.TestCase):
    def test_query_in_the_new_alphabet_finds_old_names(self):
        import database
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=0)
        conn.fetch = AsyncMock(return_value=[])

        class Pool:
            def acquire(self):
                class Ctx:
                    async def __aenter__(self):
                        return conn

                    async def __aexit__(self, *a):
                        return False
                return Ctx()

        with patch.object(database, "pool", Pool()):
            run(database.search_products("şokolad"))
            run(database.admin_search_products("Çoy"))
        self.assertIn("%shokolad%", conn.fetchval.await_args.args)
        self.assertIn("%Choy%", conn.fetch.await_args.args)


class PagesTest(unittest.TestCase):
    def test_the_switch_reaches_both_pages(self):
        import admin_web
        import webapp_server
        alphabet._state["on"] = True
        mini = run(webapp_server.index(MagicMock()))
        self.assertIn('const NEW_ALPHABET = "1" === "1";', mini.text)
        alphabet._state["on"] = False
        panel = run(admin_web.admin_page(MagicMock()))
        self.assertIn('const NEW_ALPHABET = "0" === "1";', panel.text)
        alphabet._state["on"] = True


if __name__ == "__main__":
    unittest.main()
