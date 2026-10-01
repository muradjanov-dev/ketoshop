"""Shaxsiy tavsiyalar (product_tips.py) va qayta sotuvdagi ⭐ fikr so'rash /
💡 tavsiya xabarlari — bazaga va Telegram'ga ulanmasdan."""
import os
import re
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import product_tips as t
import retention

NOW = datetime(2026, 10, 2, 5, 0)


def order(oid, days_ago, items, status="delivered"):
    at = NOW - timedelta(days=days_ago)
    return {"id": oid, "status": status, "created_at": at,
            "delivered_at": at if status == "delivered" else None, "items": items}


def line(pid, name, price=50000, qty=1, **extra):
    return dict({"product_id": pid, "name": name, "price": price, "quantity": qty}, **extra)


GHEE = line(11, "Tabiiy GHEE 1000ml")
GIFT = line(5, "Eritritol 100gr", price=0, is_bonus=True, is_gift=True)
DEVZIRA = {"id": 50, "name": "Qizil guruch (Devzira) (bo'yalmagan, yog'lanmagan) 1000gr",
           "name_ru": None, "quantity": 9}


class MatchingTest(unittest.TestCase):
    def test_catalogue_names(self):
        cases = {
            "Bodom uni 1000gr": "almond_flour", "Eritrtitol 1000gr": "erythritol",
            "Alluloza +Steviya 200gr": "allulose", "Toza Steviya 50gr": "stevia",
            "Qizil guruch (Devzira) 500gr": "devzira", "Basmati guruch Premium Besta 900gr": "basmati",
            "Qora guruch 1kg Tayland": "black_rice", "Tabiiy GHEE 1000ml": "ghee",
            "Зайтун ёғи совуқ сиқим- Extra vergin": "olive_oil", "Kokos uni 500gr": "coconut_flour",
            "Kokos slivka 400ml": "coconut_cream", "Kakao nibs 200gr": "cacao_nibs",
            "Qora shokolad granula 500g": "chocolate", "«Победа» 72% Dark горький": "chocolate",
            "Zig‘ir uni 400g": "flax", "Psillium uni 300gr": "psyllium", "Ksantan kamedi 200gr": "xanthan",
            "Xandonpista pastasi 200gr": "pistachio_paste", "Yeryong'oq pasta 200gr": "peanut_paste",
            "Табиий ҳамиртуруш— закваска": "sourdough", "Koritsa 70g": "cinnamon",
            "Polba uni": None,
        }
        for name, key in cases.items():
            with self.subTest(name=name):
                self.assertEqual(t.tip_key(name), key)

    def test_every_pair_has_three_variants_in_both_languages(self):
        self.assertGreaterEqual(len(t.PAIRS), 60)
        for (viewed, earlier), (uz, ru) in t.PAIRS.items():
            with self.subTest(pair=(viewed, earlier)):
                self.assertEqual(len(uz), 3)
                self.assertEqual(len(ru), 3)
                self.assertEqual(len({s.split()[0] for s in uz}), 3, "openings must differ")
                for s in uz:
                    self.assertNotIn("olgan edingiz", s)
                    self.assertNotIn("tanlagan edingiz", s)
                    self.assertNotRegex(s, r"GHEE'")      # would turn into "GHEEъ" in Cyrillic


class ChooseTest(unittest.TestCase):
    def hist(self, days=30):
        return t.history_from_orders([order(1, days, [GHEE, GIFT])])

    def test_gift_is_not_a_purchase(self):
        self.assertEqual([h["key"] for h in self.hist()], ["ghee"])

    def test_pair_line_rotates(self):
        lines = [t.choose(self.hist(5), DEVZIRA, "uz", turn, NOW) for turn in range(4)]
        self.assertEqual(len(set(lines[:3])), 3)
        self.assertEqual(lines[0], lines[3])
        self.assertIn("GHEE", lines[0])

    def test_restock_note_only_sometimes_and_only_when_old(self):
        old = [t.choose(self.hist(30), DEVZIRA, "uz", turn, NOW) for turn in range(3)]
        self.assertEqual(sum("tugab qolgan bo'lsa" in s for s in old), 1)
        fresh = [t.choose(self.hist(5), DEVZIRA, "uz", turn, NOW) for turn in range(3)]
        self.assertFalse(any("tugab qolgan" in s for s in fresh))

    def test_cyrillic_keeps_the_brand(self):
        text = t.choose(self.hist(5), DEVZIRA, "uz_cyr", 0, NOW)
        self.assertIn("GHEE", text)
        self.assertNotIn("ГҲЕЕ", text)
        self.assertIn("Девзира", text)

    def test_russian(self):
        self.assertRegex(t.choose(self.hist(5), DEVZIRA, "ru", 0, NOW), r"[а-я]{4,}")

    def test_other_size_and_general_fallback(self):
        self.assertIn(t.choose(self.hist(), {"id": 12, "name": "GHEE 500ml"}, "uz", 0, NOW), t.SIZE[0])
        # Only the free Eritritol in history → general line, not "you know eritritol"
        self.assertEqual(t.choose(self.hist(), {"id": 99, "name": "Eritritol 1000gr"}, "uz", 0, NOW),
                         t.GENERAL["erythritol"][0])
        self.assertIsNone(t.choose(self.hist(), {"id": 98, "name": "Polba uni"}, "uz", 0, NOW))

    def test_no_history_gets_general_line(self):
        self.assertEqual(t.choose([], DEVZIRA, "ru", 0, NOW), t.GENERAL["devzira"][1])

    def test_rotation_only_on_fresh_open(self):
        t._turns.clear()
        a = t.next_turn(1, 50, advance=True)
        b = t.next_turn(1, 50, advance=False)      # +/- repaint
        c = t.next_turn(1, 50, advance=True)       # next visit
        self.assertEqual(a, b)
        self.assertEqual(c, a + 1)


AVAILABLE = {("p", 50): DEVZIRA,
             ("p", 60): {"id": 60, "name": "Bodom uni 1000gr", "name_ru": None, "quantity": 3}}


def ctx(**over):
    base = {"product_medians": {}, "shop_median": 30, "available": AVAILABLE, "pairs": {},
            "sent_refs": set(), "offer": None, "last_message_at": None,
            "cart_touched_at": None, "cart_reminded_at": None, "opted_out": False,
            "reviewed": set()}
    base.update(over)
    return base


class ReviewAskTest(unittest.TestCase):
    TEN = [line(100 + i, f"Mahsulot {i}", price=10000 * (i + 1)) for i in range(10)] + [GIFT]

    def test_ten_products_four_buttons_plus_other(self):
        orders = [order(1, 40, [line(109, "Mahsulot 9", price=100000)]), order(2, 3, self.TEN)]
        plan = retention.plan_for_user(1, orders, NOW, ctx(available={}))
        self.assertEqual(plan["kind"], "review_ask")
        ids = [p["id"] for p in plan["review_items"]]
        self.assertNotIn(5, ids)                          # the gift is not asked about
        self.assertEqual(ids[0], 108)                     # newest-to-them, priciest first
        self.assertEqual(ids[-1], 109)                    # bought before → asked last
        kb = retention.build_keyboard(plan, "uz", 1, None)
        cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
        self.assertEqual(sum(c.startswith("write_review:") for c in cbs), retention.REVIEW_BUTTONS)
        self.assertIn("review_order:2", cbs)
        self.assertIn("rt_off", cbs)

    def test_reviewed_products_are_skipped_and_window_is_respected(self):
        one = [line(7, "Bodom uni 1000gr")]
        self.assertIsNone(retention.plan_for_user(1, [order(1, 4, one), order(0, 60, one)], NOW,
                                                  ctx(available={}, reviewed={7})))
        self.assertIsNone(retention.plan_for_user(1, [order(1, 2, one), order(0, 60, one)], NOW,
                                                  ctx(available={})))

    def test_first_order_keeps_its_thank_you(self):
        plan = retention.plan_for_user(1, [order(1, 4, [line(7, "Bodom uni 1000gr")])], NOW, ctx())
        self.assertEqual(plan["kind"], "second_checkin")

    def test_text_in_three_languages(self):
        plan = {"kind": "review_ask", "days": 3, "order_id": 2, "first_name": "Aziz",
                "review_items": [{"id": 1, "name": "Bodom uni 1000gr", "name_ru": "Миндальная мука"}]}
        uz = retention.build_text(plan, "uz", gift=None, offer=None, also=None, quick_ready=False)
        self.assertIn("sifatini qanday baholaysiz", uz)
        self.assertIn("mazali taomlar pishirib ko'rdingizmi", uz)
        self.assertIn("Aziz, buyurtmangiz", uz)
        ru = retention.build_text(plan, "ru", gift=None, offer=None, also=None, quick_ready=False)
        self.assertIn("качество наших продуктов", ru)
        cyr = retention.build_text(plan, "uz_cyr", gift=None, offer=None, also=None, quick_ready=False)
        self.assertNotRegex(cyr, r"[a-z]{4,}")


class TavsiyaTest(unittest.TestCase):
    def test_pick_between_orders(self):
        orders = [order(1, 15, [GHEE, GIFT])]
        plan = retention.plan_for_user(1, orders, NOW, ctx())
        self.assertEqual(plan["kind"], "tavsiya")
        self.assertEqual(plan["target"]["id"], 50)        # Devzira pairs with GHEE
        too_soon = retention.plan_for_user(1, [order(1, 5, [GHEE])], NOW, ctx())
        self.assertNotEqual((too_soon or {}).get("kind"), "tavsiya")
        # Never the same product twice — the next pairing comes instead…
        nxt = retention.plan_for_user(1, orders, NOW, ctx(sent_refs={"tavsiya:50"}))
        self.assertEqual(nxt["target"]["id"], 60)         # Bodom uni also pairs with GHEE
        # …and once every pairing was used, nothing.
        self.assertIsNone(retention.plan_for_user(1, orders, NOW, ctx(sent_refs={"tavsiya:50", "tavsiya:60"})))

    def test_message(self):
        plan = retention.plan_for_user(1, [order(1, 15, [GHEE])], NOW, ctx())
        plan["first_name"] = "Aziz"
        for lang in ("uz", "uz_cyr", "ru"):
            text = retention.build_text(plan, lang, gift=None, offer=None, also=None, quick_ready=False)
            kb = retention.build_keyboard(plan, lang, 1, None)
            with self.subTest(lang=lang):
                self.assertIn("💡", text)
                self.assertTrue(any(b.callback_data == "product:50"
                                    for row in kb.inline_keyboard for b in row))
                self.assertNotIn("olgan edingiz", text)
        self.assertIn("GHEE", retention.build_text(plan, "uz_cyr", gift=None, offer=None,
                                                   also=None, quick_ready=False))


if __name__ == "__main__":
    unittest.main()
