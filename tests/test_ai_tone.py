"""ai_tone.vary — oldingi javobdagi qolip ketma-ket qaytarilmaydi (egasi,
2026-11-08: "robotga o'xshab faqat tasdiqlayvermasin")."""
import asyncio
import os
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import ai_sales  # noqa: E402
import ai_tone  # noqa: E402
import database  # noqa: E402

vary = ai_tone.vary


class YesOpenerTest(unittest.TestCase):
    def test_second_yes_in_a_row_is_dropped(self):
        prev = "Ha, kompot uchun ham mumkin. Faqat oz-ozdan solinadi."
        self.assertEqual(
            vary("Ha, to'g'ri saqlansa uzoq turadi.\n\nQuruq, salqin joyda saqlang.", prev),
            "To'g'ri saqlansa uzoq turadi.\n\nQuruq, salqin joyda saqlang.")
        self.assertEqual(vary("Ha, albatta bor 😊 Bizda ikki xil:", prev), "Bor 😊 Bizda ikki xil:")
        self.assertEqual(vary("Albatta, kompotga ham bo'ladi.", prev), "Kompotga ham bo'ladi.")

    def test_a_single_yes_stays(self):
        reply = "Ha, mumkin. Kompotga ozdan soling."
        self.assertEqual(vary(reply, "Stevia bizda 4 xil:\n\n• Stevia 200gr - 33 000 so'm"), reply)
        self.assertEqual(vary(reply, None), reply)

    def test_russian_and_cyrillic(self):
        self.assertEqual(vary("Да, хранится долго, если держать в сухом месте.",
                              "Да, для выпечки подойдёт."),
                         "Хранится долго, если держать в сухом месте.")
        self.assertEqual(vary("Конечно, подойдёт и для крема.", "Да, подойдёт."),
                         "Подойдёт и для крема.")
        self.assertEqual(vary("Ҳа, узоқ сақланади, қуруқ жойда турса бўлди.", "Ҳа, мумкин."),
                         "Узоқ сақланади, қуруқ жойда турса бўлди.")

    def test_words_that_only_begin_with_ha_are_not_touched(self):
        prev = "Ha, bor."
        for reply in ("Hamma mahsulot quruq joyda turadi.", "Xamirga 2 qoshiq soling.",
                      "Haqiqatan ham shirin bo'ladi."):
            self.assertEqual(vary(reply, prev), reply)
        self.assertEqual(vary("Давайте подберём вариант.", "Да, есть."), "Давайте подберём вариант.")

    def test_nothing_else_left_keeps_the_reply(self):
        self.assertEqual(vary("Ha 😊", "Ha, bor."), "Ha 😊")


class CartQuestionTest(unittest.TestCase):
    PREV = "Stevia 200gr - 33 000 so'm.\n\nQaysi hajmi kerak edi? Savatga qo'shamizmi? 🛒"

    def test_repeated_cart_question_is_dropped_but_the_rest_of_the_line_stays(self):
        reply = ("Kompotga ham bo'ladi, faqat ozdan soling.\n\n"
                 "• Stevia 200gr - 33 000 so'm\n\nQaysi biri kerak? Savatga qo'shamizmi? 🛒")
        self.assertEqual(vary(reply, self.PREV),
                         "Kompotga ham bo'ladi, faqat ozdan soling.\n\n"
                         "• Stevia 200gr - 33 000 so'm\n\nQaysi biri kerak?")

    def test_a_cart_question_on_its_own_line_goes_with_the_line(self):
        reply = "Quruq joyda yaxshi turadi.\n\nSavatga qo'shib qo'yaymi? 🛒"
        self.assertEqual(vary(reply, self.PREV), "Quruq joyda yaxshi turadi.")

    def test_first_cart_question_and_cart_statements_stay(self):
        reply = "Stevia 200gr - 33 000 so'm. Savatga qo'shamizmi? 🛒"
        self.assertEqual(vary(reply, "Steviya shakardan ancha shirin."), reply)
        self.assertEqual(vary("Savatga qo'shdik 👍", self.PREV), "Savatga qo'shdik 👍")

    def test_russian_and_cyrillic(self):
        self.assertEqual(vary("Хорошо хранится в сухом месте. Добавим в корзину? 🛒",
                              "Эритритол 500гр - 68 000 сум. Добавим в корзину? 🛒"),
                         "Хорошо хранится в сухом месте.")
        self.assertEqual(vary("Компотга ҳам бўлади.\n\nСаватга қўшамизми? 🛒", "Саватга қўшамизми? 🛒"),
                         "Компотга ҳам бўлади.")


class EmptyOfferTest(unittest.TestCase):
    def test_second_tell_you_later_offer_is_dropped(self):
        prev = "Toza Steviya juda oz solinadi.\n\nAgar xohlasangiz, kompot uchun qulayrog'ini ham aytib beramiz."
        reply = ("200 gramm uzoq yetadi. Agar xohlasangiz, kuniga qancha ishlatishingizga qarab "
                 "taxmin qilib beramiz.")
        self.assertEqual(vary(reply, prev), "200 gramm uzoq yetadi.")

    def test_offers_that_ask_to_act_stay(self):
        prev = "Agar xohlasangiz, retseptini ham aytib beramiz."
        reply = "Xohlasangiz, shu tarkibni savatga solib buyurtma kartasini ochib beramiz."
        self.assertEqual(vary(reply, prev), reply)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class AnswerPipelineTest(unittest.TestCase):
    """_answer: javob oldingisi bilan solishtiriladi va oxirgisi eslab qolinadi."""

    def setUp(self):
        import ai_stats
        self._orig = [(ai_stats, "record_turn", ai_stats.record_turn),
                      (database, "get_user_language", database.get_user_language),
                      (ai_sales, "_respond", ai_sales._respond),
                      (ai_sales, "_mirror", ai_sales._mirror)]
        ai_stats.record_turn = AsyncMock()
        database.get_user_language = AsyncMock(return_value="uz")
        ai_sales._mirror = AsyncMock()
        ai_sales._sessions.clear()

    def tearDown(self):
        for obj, name, value in self._orig:
            setattr(obj, name, value)
        ai_sales._sessions.clear()

    def test_two_replies_in_a_row(self):
        sent = []

        async def answer(text, reply_markup=None, **_):
            sent.append(text)
        message = NS(from_user=NS(id=4242, full_name="Mijoz", username=None, first_name="Mijoz"),
                     chat=NS(id=4242, type="private"), text="", answer=answer)
        ai_sales._sessions[4242] = ai_sales._session(4242)
        replies = iter(["Ha, kompotga ham bo'ladi. Savatga qo'shamizmi? 🛒",
                        "Ha, quruq joyda uzoq turadi. Savatga qo'shamizmi? 🛒"])

        async def respond(bot, msg, text):
            return next(replies)
        ai_sales._respond = respond
        _run(ai_sales._answer(None, message, "kompotga mumkinmi"))
        _run(ai_sales._answer(None, message, "uzoq saqlanadimi"))
        self.assertEqual(sent, ["Ha, kompotga ham bo'ladi. Savatga qo'shamizmi? 🛒",
                                "Quruq joyda uzoq turadi."])
        self.assertEqual(ai_sales._sessions[4242]["last_reply"], "Quruq joyda uzoq turadi.")


if __name__ == "__main__":
    unittest.main()
