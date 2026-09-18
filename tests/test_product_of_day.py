"""Kun mahsuloti: navbatdagi mahsulot tanlovi va kanal havolasi."""
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import product_card
import product_of_day as pod


def product(pid=1, qty=10, views=0, discount=0, photo="file_id"):
    return {"id": pid, "quantity": qty, "views_30d": views,
            "discount_percent": discount, "discount_until": None,
            "photo_id": photo}


class ScoreTest(unittest.TestCase):
    def test_discount_outranks_plain(self):
        self.assertGreater(pod.score(product(discount=20), {}),
                           pod.score(product(), {}))

    def test_attention_outranks_ignored(self):
        self.assertGreater(pod.score(product(views=40), {}),
                           pod.score(product(views=0), {}))

    def test_sales_count(self):
        self.assertGreater(pod.score(product(pid=7), {7: 20}),
                           pod.score(product(pid=7), {}))

    def test_nearly_out_of_stock_is_pushed_back(self):
        # Spotlighting three remaining units buys cancelled orders, not sales.
        self.assertLess(pod.score(product(qty=2), {}),
                        pod.score(product(qty=10), {}))

    def test_a_photo_beats_no_photo(self):
        self.assertGreater(pod.score(product(), {}),
                           pod.score(product(photo=None), {}))

    def test_attention_is_capped(self):
        # One viral product must not own the spotlight forever — a discounted
        # in-stock rival still gets its turn.
        self.assertLess(pod.score(product(views=10_000), {}),
                        pod.score(product(views=100, discount=30), {}) + 10)


class PayloadTest(unittest.TestCase):
    def test_reads_own_payload(self):
        self.assertEqual(product_card.parse_product_payload("prod_42"), 42)

    def test_ignores_other_deep_links(self):
        for other in ("fb_yanvar", "ig_story", "ref77", "aziza", "", None):
            self.assertIsNone(product_card.parse_product_payload(other), other)

    def test_bloggers_do_not_claim_it(self):
        import bloggers
        self.assertIsNone(bloggers.parse_payload("prod_42"))

    def test_link_points_at_the_bot(self):
        self.assertTrue(product_card.product_link(42).endswith("?start=prod_42"))


class ChannelKeyboardTest(unittest.TestCase):
    def test_url_button_not_callback(self):
        # A channel reader may never have opened the bot, so a callback button
        # would do nothing for them — it has to be a link.
        btn = pod.channel_keyboard(42).inline_keyboard[0][0]
        self.assertIsNone(btn.callback_data)
        self.assertEqual(btn.url, product_card.product_link(42))

    def test_channel_label_is_cyrillic(self):
        btn = pod.channel_keyboard(42).inline_keyboard[0][0]
        self.assertIn("Ботда", btn.text)


if __name__ == "__main__":
    unittest.main()
