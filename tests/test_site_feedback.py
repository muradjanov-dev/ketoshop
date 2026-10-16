"""Sayt haqida fikr: validatsiya, adminlarga xabar, takroriy yuborish."""
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import site_feedback
import webapp_server


class ParseTests(unittest.TestCase):
    def test_accepts_stars_comment_or_both(self):
        self.assertEqual(site_feedback.parse({"rating": 5, "comment": ""}), (5, ""))
        self.assertEqual(site_feedback.parse({"rating": 0, "comment": "  Qulay  "}), (0, "Qulay"))
        self.assertEqual(site_feedback.parse({"rating": 3, "comment": "Yaxshi"}), (3, "Yaxshi"))

    def test_rejects_nothing_to_send_and_bad_values(self):
        for data in ({"rating": 0, "comment": "   "}, {}, {"rating": 6}, {"rating": -1},
                     {"rating": True}, {"rating": "5"}, {"rating": 4, "comment": 12}, ["x"], None):
            self.assertIsNone(site_feedback.parse(data), data)

    def test_long_comment_is_cut(self):
        rating, comment = site_feedback.parse({"rating": 4, "comment": "a" * 5000})
        self.assertEqual(len(comment), site_feedback.MAX_COMMENT)


class AllowTests(unittest.TestCase):
    def setUp(self):
        site_feedback._last_sent.clear()

    def test_one_per_cooldown(self):
        self.assertTrue(site_feedback.allow(7, now=1000.0))
        self.assertFalse(site_feedback.allow(7, now=1000.0 + site_feedback.COOLDOWN - 1))
        self.assertTrue(site_feedback.allow(7, now=1000.0 + site_feedback.COOLDOWN + 1))
        self.assertTrue(site_feedback.allow(8, now=1001.0))


class AdminTextTests(unittest.TestCase):
    def test_stars_name_and_escaping(self):
        text = site_feedback.admin_text({"first_name": "Ali <b>", "username": "ali_v"}, 42, 4,
                                        "Zo'r <script>x</script> & tez", "uz_cyr")
        self.assertIn("⭐⭐⭐⭐  <b>4/5</b>", text)
        self.assertIn("Ali &lt;b&gt; · @ali_v", text)
        self.assertIn("Zo&#x27;r &lt;script&gt;x&lt;/script&gt; &amp; tez", text)
        self.assertIn("<code>42</code>", text)
        self.assertIn("o'zbek (kirill)", text)

    def test_comment_only_and_unknown_user(self):
        text = site_feedback.admin_text(None, 9, 0, "Qidiruv qulay", "ru")
        self.assertIn("yulduzcha qo'yilmadi", text)
        self.assertIn("ID 9", text)
        self.assertIn("rus", text)


class EndpointTests(unittest.IsolatedAsyncioTestCase):
    class Request(dict):
        def __init__(self, body, bot, user_id=101):
            super().__init__({"user_id": user_id, "user_lang": "uz",
                              "telegram_user": {"id": user_id, "first_name": "Malika"}})
            self._body = body
            self.app = {"bot": bot}

        async def json(self):
            if isinstance(self._body, Exception):
                raise self._body
            return self._body

    def setUp(self):
        site_feedback._last_sent.clear()

    async def test_feedback_reaches_every_admin_once(self):
        bot = AsyncMock()
        with patch.object(site_feedback, "ADMIN_IDS", [1, 2, 2]):
            resp = await webapp_server.api_site_feedback(self.Request({"rating": 5, "comment": "Juda qulay"}, bot))
            self.assertEqual(resp.status, 200)
            self.assertEqual(bot.send_message.await_count, 2)
            sent_text = bot.send_message.await_args.args[1]
            self.assertIn("Sayt haqida yangi fikr", sent_text)
            self.assertIn("Juda qulay", sent_text)
            self.assertIn("Malika", sent_text)

            # A second send inside the cooldown is accepted but not relayed.
            bot.send_message.reset_mock()
            resp = await webapp_server.api_site_feedback(self.Request({"rating": 1}, bot))
            self.assertEqual(resp.status, 200)
            bot.send_message.assert_not_awaited()

    async def test_empty_or_broken_body_is_rejected(self):
        bot = AsyncMock()
        with patch.object(site_feedback, "ADMIN_IDS", [1]):
            resp = await webapp_server.api_site_feedback(self.Request({"rating": 0, "comment": ""}, bot))
            self.assertEqual(resp.status, 400)
            resp = await webapp_server.api_site_feedback(self.Request(ValueError("bad json"), bot))
            self.assertEqual(resp.status, 400)
        bot.send_message.assert_not_awaited()

    async def test_one_admin_failing_does_not_stop_the_rest(self):
        bot = AsyncMock()
        bot.send_message.side_effect = [Exception("blocked"), None]
        with patch.object(site_feedback, "ADMIN_IDS", [1, 2]):
            resp = await webapp_server.api_site_feedback(self.Request({"rating": 3}, bot, user_id=202))
        self.assertEqual(resp.status, 200)
        self.assertEqual(bot.send_message.await_count, 2)

    def test_route_is_registered(self):
        app = webapp_server.create_webapp(object())  # type: ignore[arg-type]
        routes = {(r.method, r.resource.canonical) for r in app.router.routes()}
        self.assertIn(("POST", "/api/site-feedback"), routes)


if __name__ == "__main__":
    unittest.main()
