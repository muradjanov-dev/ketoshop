"""Sirli sovg'a eslatmasi har bir admin kartasida + savat matnidagi hisob
(egasi, 2026-11-02).

* 400 000 so'mdan yuqori buyurtmada «🎁 SIRLI SOVG'A — qutiga soling» faqat
  birinchi "yangi buyurtma" xabarida emas, ochilgan buyurtma kartasida va
  holat kartalarida ham turadi; admin kiritgan (manual/b2b) va 🧪 test
  buyurtmalarda — yo'q.
* Sovg'a qatori «15 000 0» bo'lib "150 000" deb o'qilmasin: so'm va → bilan.
* Miqdor «2.0 dona» emas, «2 dona».
"""
import asyncio
import json
import os
import unittest
from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import handlers.seller as seller
import mystery_gift
import order_admin_feed as feed
import promotions
from handlers.cart import _fmt_qty

ADMIN = 4242
# The cart from the owner's screenshot: 406 000 so'm of goods + the free Eritritol.
ITEMS = [
    {"product_id": 1, "name": "Guruch uni", "quantity": 2.0, "price": 20000, "unit": "dona"},
    {"product_id": 2, "name": "Yashil grechka uni 1000gr", "quantity": 1.0, "price": 48000, "unit": "dona"},
    {"product_id": 3, "name": "Oq zig'ir uni 1000gr", "quantity": 1.0, "price": 55000, "unit": "dona"},
    {"product_id": 4, "name": "Zig'ir uni 1000gr", "quantity": 1.0, "price": 37000, "unit": "dona"},
    {"product_id": 5, "name": "Tabiiy GHEE 1000ml", "quantity": 1.0, "price": 122000, "unit": "litr"},
    {"product_id": 6, "name": "Himalay tuz 1000gr", "quantity": 1.0, "price": 28000, "unit": "dona"},
    {"product_id": 7, "name": "Stevia 500g", "quantity": 1.0, "price": 76000, "unit": "dona"},
    {"product_id": 8, "name": "Eritritol 100gr", "quantity": 1, "price": 0, "is_bonus": True},
]
ORDER = {"id": 801, "user_id": 555, "seller_id": None, "status": "confirmed", "total": 406000,
         "items": json.dumps(ITEMS), "customer_name": "Ali", "phone": "+998900000000",
         "address": "Toshkent", "delivery_method": "self", "source": "bot",
         "created_at": datetime(2026, 11, 2, 9, 0), "confirmed_at": None,
         "shipped_at": None, "delivered_at": None}


class GiftNoteTest(unittest.TestCase):
    def test_note_from_the_saved_order(self):
        self.assertIn("SIRLI SOVG'A", mystery_gift.order_admin_note(ORDER, "uz"))
        self.assertIn("ТАИНСТВЕННЫЙ", mystery_gift.order_admin_note(ORDER, "ru"))

    def test_no_note_below_the_line_or_for_admin_entered_orders(self):
        small = dict(ORDER, items=json.dumps(ITEMS[:3]))
        self.assertEqual(mystery_gift.order_admin_note(small, "uz"), "")
        for source in ("manual", "b2b", "test"):
            self.assertEqual(mystery_gift.order_admin_note(dict(ORDER, source=source), "uz"), "")
        self.assertIn("SIRLI", mystery_gift.order_admin_note(dict(ORDER, source=None), "uz"))
        self.assertEqual(mystery_gift.order_admin_note(dict(ORDER, items="not json"), "uz"), "")

    def test_status_card_carries_the_note(self):
        text = feed.build_card(ORDER, "uz", title="status_title", by="Admin",
                               old_status="pending", new_status="confirmed")
        self.assertIn("SIRLI SOVG'A", text)

    def test_opened_order_card_carries_the_note(self):
        msg = NS(edit_text=AsyncMock(), answer=AsyncMock(), photo=None)
        cb = NS(data="seller_order:801", from_user=NS(id=ADMIN), message=msg, answer=AsyncMock())
        with patch.object(seller, "ADMIN_IDS", [ADMIN]), \
             patch.object(seller, "get_user_language", AsyncMock(return_value="uz")), \
             patch.object(seller, "get_order", AsyncMock(return_value=dict(ORDER))), \
             patch.object(seller, "get_user", AsyncMock(return_value=None)), \
             patch("handlers.cart.order_history_block", AsyncMock(return_value="")):
            asyncio.run(seller.view_seller_order(cb))
        text = msg.edit_text.call_args.args[0]
        self.assertIn("SIRLI SOVG'A", text)
        self.assertIn("Yashil grechka uni 1000gr — 1 × 48 000", text)   # 1, not 1.0
        self.assertIn("Guruch uni — 2 × 20 000", text)


class CartTextTest(unittest.TestCase):
    def test_gift_price_cannot_be_read_as_150_000(self):
        line = promotions.bonus_price_html({"bonus_value": 15000}, "uz")
        self.assertEqual(line, "<s>15 000 so'm</s> → <b>bepul</b>")
        plain = line.replace("<s>", "").replace("</s>", "").replace("<b>", "").replace("</b>", "")
        self.assertNotIn("15 000 0", plain)
        self.assertEqual(promotions.bonus_price_html({"bonus_value": 15000}, "ru"),
                         "<s>15 000 сум</s> → <b>бесплатно</b>")
        self.assertEqual(promotions.bonus_price_html({"bonus_value": 0}, "uz"), "bepul")

    def test_whole_quantities_read_whole(self):
        self.assertEqual(_fmt_qty(2.0), "2")
        self.assertEqual(_fmt_qty(1.5), "1.5")


if __name__ == "__main__":
    unittest.main()
