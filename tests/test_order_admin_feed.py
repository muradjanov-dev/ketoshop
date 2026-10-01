import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")

import order_admin_feed as feed

ORDER = {
    "id": 512, "status": "shipped", "customer_name": "Ali <Valiyev>",
    "phone": "+998901234567", "address": "Toshkent, Chilonzor 5", "total": 345000,
    "items": '[{"name": "Bodom uni 1000gr", "quantity": 2, "price": 150000, "unit": "dona"},'
             ' {"name": "Eritritol 100gr", "quantity": 1, "price": 0, "is_bonus": true},'
             ' {"name": "Zig\'ir uni", "quantity": 0.5, "price": 90000, "unit": "kg"}]',
}


class OrderCardTest(unittest.TestCase):
    def card(self, lang="uz", **kw):
        kw.setdefault("title", "status_title")
        kw.setdefault("by", "Nodir (@nodir)")
        return feed.build_card(ORDER, lang, **kw)

    def test_status_change_lists_everything(self):
        text = self.card(old_status="confirmed", new_status="shipped")
        self.assertIn("#512", text)
        self.assertIn("→", text)
        self.assertIn("Bodom uni 1000gr × 2 — 300 000", text)
        self.assertIn("Eritritol 100gr × 1 — 🎁 bepul", text)
        self.assertIn("× 0.5 kg — 45 000", text)
        self.assertIn("345 000 so'm", text)
        self.assertIn("Nodir (@nodir)", text)
        self.assertIn("+998901234567", text)

    def test_customer_text_is_escaped(self):
        self.assertIn("Ali &lt;Valiyev&gt;", self.card())
        self.assertNotIn("<Valiyev>", self.card())

    def test_cyrillic_template_keeps_names(self):
        text = self.card("uz_cyr", old_status="confirmed", new_status="shipped")
        self.assertIn("Буюртма #512", text)
        self.assertIn("Nodir (@nodir)", text)       # the person's name is not transliterated
        self.assertIn("Bodom uni 1000gr", text)     # nor the product as stored

    def test_manual_card_shows_creator_and_status(self):
        text = self.card(title="manual_title")
        self.assertIn("Qo'lda yangi buyurtma #512", text)
        self.assertIn("Holati:", text)

    def test_fits_one_message_even_when_huge(self):
        import json
        big = dict(ORDER, items=json.dumps([{"name": f"Mahsulot {i}", "quantity": 1, "price": 1000}
                                            for i in range(200)]))
        text = feed.build_card(big, "uz", title="b2b_title", by="x")
        self.assertLess(len(text), 4096)
        self.assertIn("yana 175 ta", text)

    def test_actor(self):
        self.assertEqual(feed.actor(SimpleNamespace(full_name="Nodir", username="nodir", id=1)),
                         "Nodir (@nodir)")
        self.assertEqual(feed.actor(SimpleNamespace(full_name="Aziz", username=None, id=2)), "Aziz")
        self.assertEqual(feed.actor("Sayt — Kuryer doskasi"), "Sayt — Kuryer doskasi")

    def test_no_send_without_bot_or_change(self):
        # Neither call may schedule anything (no running loop is needed for that).
        feed.status_changed(None, 1, "pending", "confirmed", "x")
        feed.status_changed(object(), 1, "cancelled", "cancelled", "x")
        feed.manual_created(None, 1, "x")
        self.assertEqual(len(feed._tasks), 0)


if __name__ == "__main__":
    unittest.main()
