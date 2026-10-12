"""Reklama samarasi (ads_impact.py) — Meta'ga ham, bazaga ham ulanmasdan.

Tekshiriladi: Graph qatorini o'qish, videoni mahsulotga bog'lash (nom, o'zak,
kirill), korrelyatsiya, sotuv bloki faqat O'SISHNI reklamaga yozishi, videolar
reytingi va "NIMA QILISH KERAK", mahsulotlar o'sishi, kunlik bog'liqlik
xulosalari, bazadan kunlik sotuv (sovg'a/bonus qatorlari sanalmaydi) va
/reklama hisoboti bazasiz ham chiqishi.
"""
import asyncio
import contextlib
import json
import os
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import ads_impact
import database
import meta_ads

CATALOG = {
    10: {"id": 10, "name": "Eritritol 500gr", "name_ru": "Эритрит 500г", "quantity": 4},
    11: {"id": 11, "name": "Eritritol 100gr", "name_ru": "Эритрит 100г", "quantity": 50},
    20: {"id": 20, "name": "Bodom uni 1kg", "name_ru": "Миндальная мука 1кг", "quantity": 30},
    30: {"id": 30, "name": "Keto non", "name_ru": None, "quantity": 30},
    40: {"id": 40, "name": "Psillium 250gr", "name_ru": "Псиллиум 250г", "quantity": 30},
}


def _ad(name, spend, *, messages=0, clicks=0, reach=1000, families=(), ad_id="1"):
    return {"id": ad_id, "name": name, "spend": spend, "impressions": reach * 2,
            "reach": reach, "clicks": clicks, "ctr": 1.5, "views": 500, "thruplays": 100,
            "messages": messages, "leads": 0, "families": list(families)}


def _totals(orders=0, revenue=0.0, new_users=0, ad_users=0, products=None):
    return {"orders": orders, "revenue": revenue, "new_users": new_users,
            "ad_users": ad_users, "products": products or {}}


class GraphRowTest(unittest.TestCase):
    def test_reads_messages_views_and_thruplays(self):
        row = {
            "ad_id": "7", "ad_name": "Eritritol video", "spend": "12.50", "reach": "4000",
            "impressions": "6000", "inline_link_clicks": "80", "ctr": "1.33",
            "actions": [
                {"action_type": "video_view", "value": "900"},
                {"action_type": "onsite_conversion.messaging_conversation_started_7d", "value": "25"},
                {"action_type": "lead", "value": "2"},
            ],
            "video_thruplay_watched_actions": [{"action_type": "video_view", "value": "300"}],
        }
        m = ads_impact.ad_metrics(row)
        self.assertEqual((m["spend"], m["views"], m["thruplays"], m["messages"], m["leads"]),
                         (12.5, 900, 300, 25, 2))
        self.assertEqual(m["clicks"], 80)

    def test_missing_fields_are_zero_not_crash(self):
        m = ads_impact.ad_metrics({"ad_name": "x"})
        self.assertEqual(m["spend"], 0.0)
        self.assertEqual(m["messages"], 0)

    def test_result_type_is_shared_by_all_ads(self):
        ads = [_ad("a", 5, messages=10, clicks=50), _ad("b", 5, clicks=80)]
        self.assertEqual(ads_impact.pick_result(ads)[0], "messages")
        self.assertEqual(ads_impact.pick_result([_ad("b", 5, clicks=80)])[0], "clicks")

    def test_ranking_puts_cheapest_first_and_resultless_last(self):
        ads = [_ad("dear", 10, messages=5), _ad("none", 8), _ad("cheap", 10, messages=20)]
        names = [a["name"] for a in ads_impact.rank_ads(ads, "messages")]
        self.assertEqual(names, ["cheap", "dear", "none"])


class ProductMatchTest(unittest.TestCase):
    def setUp(self):
        self.fam = ads_impact.build_families(CATALOG)

    def test_family_is_first_meaningful_word(self):
        self.assertEqual(ads_impact.product_key("Eritritol 500gr"), "eritritol")
        self.assertEqual(ads_impact.product_key("Keto bodom uni"), "bodom")
        self.assertIsNone(ads_impact.product_key("Keto set 2"))
        # Har xil qadoqlar bitta oila
        self.assertEqual(self.fam["of_product"][10], self.fam["of_product"][11])

    def test_matches_uzbek_suffixes_and_cyrillic_captions(self):
        self.assertEqual(ads_impact.families_in_text("Eritritoldan tayyorlangan desert", self.fam),
                         ["eritritol"])
        self.assertIn("eritritol", ads_impact.families_in_text("Эритрит — шакар ўрнига", self.fam))
        self.assertIn("psillium", ads_impact.families_in_text("ПСИЛЛИУМ билан нон", self.fam))

    def test_generic_words_do_not_match_every_product(self):
        self.assertEqual(ads_impact.families_in_text("Keto hayot tarzi — video 3", self.fam), [])

    def test_title_keeps_catalog_spelling(self):
        self.assertEqual(ads_impact.family_title("eritritol", CATALOG, self.fam), "Eritritol")


class CorrelationTest(unittest.TestCase):
    def test_pearson(self):
        self.assertAlmostEqual(ads_impact.pearson([1, 2, 3, 4, 5], [2, 4, 6, 8, 10]), 1.0)
        self.assertAlmostEqual(ads_impact.pearson([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]), -1.0)
        self.assertIsNone(ads_impact.pearson([1, 1, 1, 1, 1], [1, 2, 3, 4, 5]))
        self.assertIsNone(ads_impact.pearson([1, 2], [1, 2]))

    def test_next_day_effect_is_found(self):
        spend = [0, 10, 0, 10, 0, 10, 0, 10, 0]
        orders = [0, 0, 5, 0, 5, 0, 5, 0, 5]
        r, lag = ads_impact.best_lag(spend, orders)
        self.assertEqual(lag, 1)
        self.assertGreater(r, 0.9)

    def test_strength_words(self):
        self.assertEqual(ads_impact.strength(0.75), "kuchli")
        self.assertEqual(ads_impact.strength(0.4), "o'rtacha")
        self.assertEqual(ads_impact.strength(0.1), "sezilmadi")
        self.assertEqual(ads_impact.strength(None), "ma'lumot yetarli emas")


class WindowTest(unittest.TestCase):
    def test_graph_dates_win_over_local_guess(self):
        first, last = ads_impact.preset_dates(
            "last_7d", {"date_start": "2026-10-01", "date_stop": "2026-10-07"}, date(2026, 10, 12))
        self.assertEqual((first, last), (date(2026, 10, 1), date(2026, 10, 7)))

    def test_today_is_compared_with_yesterday_up_to_the_same_hour(self):
        now = datetime(2026, 10, 12, 9, 0)            # 14:00 Toshkent
        start, end = ads_impact.utc_window(date(2026, 10, 12), date(2026, 10, 12), now)
        self.assertEqual(start, datetime(2026, 10, 11, 19, 0))
        self.assertEqual(end, now)
        p_start, p_end = ads_impact.prev_window(start, end)
        # kecha 00:00–14:00 Toshkent
        self.assertEqual((p_start, p_end), (datetime(2026, 10, 10, 19, 0), datetime(2026, 10, 11, 9, 0)))

    def test_full_days_shift_by_their_length(self):
        start, end = datetime(2026, 10, 4, 19, 0), datetime(2026, 10, 11, 19, 0)
        self.assertEqual(ads_impact.prev_window(start, end), (datetime(2026, 9, 27, 19, 0), start))

    def test_daily_range_never_too_short(self):
        today = date(2026, 10, 12)
        first, last = ads_impact.daily_range("last_7d", None, today)
        self.assertEqual((last - first).days, 29)
        self.assertEqual(last, today - timedelta(days=1))


class SalesBlockTest(unittest.TestCase):
    def _block(self, cur, prev, spend=100.0, preset="last_7d"):
        return ads_impact.format_sales_block(preset, date(2026, 10, 5), date(2026, 10, 11),
                                             cur, prev, spend, 12_000.0, 7)

    def test_growth_verdict_and_only_the_increase_is_credited(self):
        text = self._block(_totals(40, 12_000_000, 120, 30), _totals(30, 9_000_000, 60, 0))
        self.assertIn("33% ko'p", text)
        self.assertIn("Qo'shimcha 10 ta buyurtma", text)
        self.assertIn("$10.00", text)                 # $100 / 10 qo'shimcha buyurtma
        self.assertIn("2.5 so'm", text)               # 3 mln / (100$ * 12 000)
        self.assertIn("Reklama havolasidan", text)
        self.assertIn("undan oldingi 7 kun", text)

    def test_average_check(self):
        text = self._block(_totals(40, 12_000_000), _totals(30, 6_000_000))
        self.assertIn("O'rtacha chek: <b>300 000</b> so'm · oldin 200 000 (▲ 50%)", text)

    def test_no_return_claimed_when_sales_fell(self):
        text = self._block(_totals(20, 5_000_000), _totals(30, 9_000_000))
        self.assertIn("kam", text)
        self.assertNotIn("Qo'shimcha", text)

    def test_maximum_is_compared_with_the_time_before_ads(self):
        text = self._block(_totals(40, 1), _totals(30, 1), preset="maximum")
        self.assertIn("reklamadan oldingi 7 kun", text)

    def test_no_spend(self):
        text = self._block(_totals(5, 1), _totals(5, 1), spend=0)
        self.assertIn("pul sarflanmagan", text)
        self.assertNotIn("Reklamaga:", text)


def _period_data(ads, cur_products, prev_products, catalog=CATALOG):
    return {"preset": "last_7d", "ads": ads, "families": ads_impact.build_families(catalog),
            "catalog": catalog, "cur": _totals(products=cur_products),
            "prev": _totals(products=prev_products), "rate": 12_000.0}


class VideosScreenTest(unittest.TestCase):
    def test_best_and_worst_with_actions(self):
        ads = [_ad("Eritritol video", 20, messages=40, families=["eritritol"]),
               _ad("Bodom video", 20, messages=5, families=["bodom"]),
               _ad("Umumiy video", 6)]
        cur = {10: {"name": "Eritritol 500gr", "qty": 12, "revenue": 1}, 11: {"name": "Eritritol 100gr", "qty": 3, "revenue": 1}}
        prev = {10: {"name": "Eritritol 500gr", "qty": 5, "revenue": 1}}
        text = ads_impact.format_videos(_period_data(ads, cur, prev))
        self.assertIn("Eng arzon natija — «Eritritol video»", text)
        self.assertIn("📦 Videoda: Eritritol — 15 dona sotildi (oldin 5, ▲ 200%)", text)
        self.assertIn("NIMA QILISH KERAK", text)
        self.assertIn("«Eritritol video» byudjetini oshiring", text)
        self.assertIn("8 marta qimmat", text)
        self.assertIn("«Umumiy video» $6.00 sarfladi", text)
        self.assertIn("omborda 4 ta qoldi", text)        # Eritritol 500gr reklamada, kam qolgan
        self.assertIn("Reklama nomiga mahsulot nomini yozing", text)
        self.assertLessEqual(len(text), 4096)

    def test_no_ads(self):
        self.assertIn("ko'rsatilmagan", ads_impact.format_videos(_period_data([], {}, {})))

    def test_ad_names_are_escaped(self):
        text = ads_impact.format_videos(_period_data([_ad("<b>x</b>", 5, clicks=3)], {}, {}))
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", text)


class ProductsScreenTest(unittest.TestCase):
    def test_growth_decline_and_ad_marker(self):
        ads = [_ad("Eritritol video", 20, messages=40, families=["eritritol"])]
        cur = {10: {"name": "Eritritol 500gr", "qty": 12, "revenue": 900_000},
               20: {"name": "Bodom uni 1kg", "qty": 9, "revenue": 1_500_000},
               40: {"name": "Psillium 250gr", "qty": 1, "revenue": 50_000}}
        prev = {10: {"name": "Eritritol 500gr", "qty": 5, "revenue": 1},
                20: {"name": "Bodom uni 1kg", "qty": 3, "revenue": 1},
                40: {"name": "Psillium 250gr", "qty": 6, "revenue": 1}}
        text = ads_impact.format_products(_period_data(ads, cur, prev))
        self.assertIn("Eng ko'p o'sgan:", text)
        self.assertIn("1. Bodom uni 1kg", text)                  # tushum bo'yicha birinchi
        self.assertIn("Eritritol 500gr: 5 → 12 dona 🎬", text)
        self.assertIn("📉", text)
        self.assertIn("Psillium 250gr: 6 → 1 dona", text)
        self.assertIn("omborda 4 ta", text)                      # 12 sotildi, 4 qoldi
        self.assertIn("«Bodom uni 1kg» reklamasiz ham o'smoqda", text)

    def test_flat_advertised_product_gets_an_action(self):
        ads = [_ad("Psillium video", 20, messages=4, families=["psillium"])]
        cur = {40: {"name": "Psillium 250gr", "qty": 2, "revenue": 1}}
        prev = {40: {"name": "Psillium 250gr", "qty": 2, "revenue": 1}}
        text = ads_impact.format_products(_period_data(ads, cur, prev))
        self.assertIn("«Psillium» videoda bor, lekin sotuvi o'smadi", text)


def _daily_data(spend_by_ad, orders, users=None, products=None, families_by_ad=None):
    n = len(orders)
    dates = [date(2026, 9, 1) + timedelta(days=i) for i in range(n)]
    days = {}
    for i, d in enumerate(dates):
        days[d.isoformat()] = {"orders": orders[i], "revenue": orders[i] * 100_000.0,
                               "new_users": (users or orders)[i], "ad_users": 0,
                               "products": (products or {}).get(i, {})}
    ads = {}
    for ad_id, series in spend_by_ad.items():
        ads[ad_id] = {"name": f"Video {ad_id}",
                      "spend": {d.isoformat(): s for d, s in zip(dates, series) if s},
                      "total": float(sum(series)),
                      "families": (families_by_ad or {}).get(ad_id, [])}
    return {"preset": "last_30d", "dates": dates, "ads": ads, "days": days,
            "catalog": CATALOG, "families": ads_impact.build_families(CATALOG), "rate": 12_000.0}


class CorrelationScreenTest(unittest.TestCase):
    def test_too_few_ad_days(self):
        text = ads_impact.format_correlation(_daily_data({"1": [0] * 27 + [5, 5, 5]}, [1] * 30))
        self.assertIn("Ma'lumot yetarli emas", text)

    def test_strong_link_and_video_to_product(self):
        pattern = [0, 4, 10, 2, 8, 0, 12, 6, 3, 9] * 3
        orders = [round(s / 2) for s in pattern]
        products = {i: {10: {"name": "Eritritol 500gr", "qty": float(s), "revenue": 1.0}}
                    for i, s in enumerate(pattern) if s}
        text = ads_impact.format_correlation(_daily_data(
            {"1": pattern}, orders, products=products, families_by_ad={"1": ["eritritol"]}))
        self.assertIn("✅ Reklama ishlayapti", text)
        self.assertIn("Sarf ↔ buyurtmalar: kuchli", text)
        self.assertIn("«Video 1» — buyurtmalar: kuchli", text)
        self.assertIn("Eritritol: kuchli (1.00)", text)
        self.assertIn("Eritritol sotuvini ko'taryapti", text)
        self.assertIn("<pre>", text)
        self.assertLessEqual(len(text), 4096)

    def test_steady_budget_is_called_out(self):
        text = ads_impact.format_correlation(_daily_data({"1": [10] * 30}, [3, 5] * 15))
        self.assertIn("bir xil byudjet", text)

    def test_no_link(self):
        spend = [0, 4, 10, 2, 8, 0, 12, 6, 3, 9] * 3
        orders = [5, 5, 1, 5, 1, 5, 1, 1, 5, 1] * 3
        text = ads_impact.format_correlation(_daily_data({"1": spend}, orders, users=[2] * 30))
        self.assertIn("bog'liqlik sezilmadi", text)


def _launch_data(capped=False):
    """01.09–30.09. «Eritritol reels» 15.09 da, «Bodom video» 18.09 da,
    «Yangi video» 29.09 da boshlangan. 15.09 dan keyin Eritritol 1 → 4 dona/kun,
    buyurtma 2 → 4, chek 100 000 → 150 000."""
    dates = [date(2026, 9, 1) + timedelta(days=i) for i in range(30)]
    days = {}
    # collect_daily sotuvni oraliqdan 7 kun oldinroqdan oladi
    for d in [date(2026, 8, 25) + timedelta(days=i) for i in range(7)] + dates:
        after = d >= date(2026, 9, 15)
        orders = 4 if after else 2
        days[d.isoformat()] = {
            "orders": orders, "revenue": orders * (150_000.0 if after else 100_000.0),
            "new_users": 1, "ad_users": 0,
            "products": {10: {"name": "Eritritol 500gr", "qty": 4.0 if after else 1.0, "revenue": 1.0},
                         20: {"name": "Bodom uni 1kg", "qty": 1.0, "revenue": 1.0}}}

    def ad(name, since, families):
        spend = {d.isoformat(): 5.0 for d in dates if d >= since}
        return {"name": name, "spend": spend, "total": sum(spend.values()), "families": families}
    ads = {"1": ad("Eritritol reels", date(2026, 9, 15), ["eritritol"]),
           "2": ad("Bodom video", date(2026, 9, 18), ["bodom"]),
           "3": ad("Yangi video", date(2026, 9, 29), []),
           "4": ad("Eski video", date(2026, 9, 1), [])}
    return {"preset": "maximum", "dates": dates, "ads": ads, "days": days, "catalog": CATALOG,
            "families": ads_impact.build_families(CATALOG), "rate": 12_000.0, "capped": capped}


class AfterVideoTest(unittest.TestCase):
    def test_week_before_vs_week_after_each_launch(self):
        effects = {e["ad"]["name"]: e for e in ads_impact.launch_effects(_launch_data())}
        e = effects["Eritritol reels"]
        self.assertEqual(e["days"], 7)
        self.assertEqual((e["before"]["orders"], e["after"]["orders"]), (14, 28))
        self.assertEqual(ads_impact.avg_check(e["before"]), 100_000)
        self.assertEqual(ads_impact.avg_check(e["after"]), 150_000)
        self.assertEqual([r["name"] for r in e["growth"]], ["Eritritol 500gr"])
        self.assertTrue(e["growth"][0]["ad"])                  # videoda ko'rsatilgan
        self.assertEqual(e["rivals"], ["Bodom video"])         # 3 kun keyin boshlangan
        self.assertTrue(effects["Yangi video"]["too_new"])     # 2 kun ishlagan
        self.assertEqual([x["ad"]["name"] for x in ads_impact.launch_effects(_launch_data())][0],
                         "Yangi video")                         # eng yangisi tepada

    def test_launch_hidden_by_the_90_day_cap_is_skipped(self):
        names = [e["ad"]["name"] for e in ads_impact.launch_effects(_launch_data(capped=True))]
        self.assertNotIn("Eski video", names)
        self.assertIn("Eski video",
                      [e["ad"]["name"] for e in ads_impact.launch_effects(_launch_data())])

    def test_screen(self):
        text = ads_impact.format_after(_launch_data())
        self.assertIn("Eng katta o'sish — «Eritritol reels» dan keyin: <b>Eritritol 500gr</b> 7 → 28 dona", text)
        self.assertIn("🎬 <b>Eritritol reels</b> · 15.09 dan", text)
        self.assertIn("🛒 Buyurtma: 14 → <b>28</b> (▲ 100%)", text)
        self.assertIn("🧾 O'rtacha chek: 100 000 → <b>150 000</b> (▲ 50%)", text)
        self.assertIn("• Eritritol 500gr: 7 → 28 dona 🎬", text)
        self.assertIn("ham boshlangan — ta'sir aralash", text)
        self.assertIn("Hali 3 kun ishlamagan", text)
        # Eritritol o'sishi 3 kun oldin boshlangan «Eritritol reels»niki — Bodom'ga yozilmaydi
        self.assertIn("• Eritritol 500gr: 16 → 28 dona (🎬 «Eritritol reels» da)", text)
        self.assertNotIn("«Bodom video» dan keyin", text)
        self.assertIn("«Eritritol reels» dan keyin Eritritol 500gr ko'proq sotildi", text)
        self.assertIn("«Eski video» dan keyin sotuv o'smadi", text)
        self.assertIn("NIMA QILISH KERAK", text)
        self.assertLessEqual(len(text), 4096)

    def test_no_videos(self):
        data = _launch_data()
        data["ads"] = {}
        self.assertIn("topilmadi", ads_impact.format_after(data))


class KeyboardTest(unittest.TestCase):
    def test_launch_view_has_no_period_buttons(self):
        kb = ads_impact.view_keyboard("aft", "last_7d")
        datas = [b.callback_data for row in kb.inline_keyboard for b in row]
        self.assertFalse(any(d.startswith("adsv:aft:") and d != "adsv:aft:last_7d" for d in datas))
        self.assertIn("ads:last_7d", datas)
        self.assertTrue(all(len(row) <= 2 for row in kb.inline_keyboard))

    def test_callback_data_fits_telegram_limit(self):
        for view, _ in ads_impact.VIEWS:
            kb = ads_impact.view_keyboard(view, "maximum")
            for row in kb.inline_keyboard:
                for b in row:
                    self.assertLessEqual(len(b.callback_data.encode()), 64)
        kb = meta_ads._period_keyboard("last_30d")
        datas = [b.callback_data for row in kb.inline_keyboard for b in row]
        self.assertIn("adsv:vid:last_30d", datas)
        self.assertIn("adsv:cor:last_30d", datas)


class _Conn:
    def __init__(self):
        self.queries = []

    async def fetch(self, sql, *args):
        self.queries.append(sql)
        if "FROM orders" in sql:
            items = [{"product_id": 10, "name": "Eritritol 500gr", "quantity": 2, "price": 75_000},
                     {"product_id": 11, "name": "Eritritol 100gr", "quantity": 1, "price": 0,
                      "is_gift": True},
                     {"product_id": 40, "name": "Psillium 250gr", "quantity": 1, "price": 0,
                      "is_bonus": True},
                     {"product_id": None, "name": "Keto set", "quantity": 1, "price": 200_000}]
            return [{"created_at": datetime(2026, 10, 10, 20, 30), "total": 350_000,
                     "items": json.dumps(items)},
                    {"created_at": datetime(2026, 10, 10, 10, 0), "total": 100_000,
                     "items": [{"product_id": 10, "name": "Eritritol 500gr", "quantity": 1,
                                "price": 75_000}]}]
        if "FROM users" in sql:
            return [{"created_at": datetime(2026, 10, 10, 18, 59)}]
        if "FROM ad_referrals" in sql:
            return [{"created_at": datetime(2026, 10, 10, 19, 0)}]
        return [dict(v) for v in CATALOG.values()]


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        @contextlib.asynccontextmanager
        async def _cm():
            yield self.conn
        return _cm()


class SalesDailyTest(unittest.TestCase):
    def test_groups_by_tashkent_day_and_skips_gift_lines(self):
        conn = _Conn()
        with patch.object(database, "pool", _Pool(conn)):
            out = asyncio.run(database.get_sales_daily(datetime(2026, 10, 1), datetime(2026, 10, 12)))
        days = out["days"]
        # 20:30 UTC = ertasi kun 01:30 Toshkent
        self.assertEqual(days["2026-10-11"]["orders"], 1)
        self.assertEqual(days["2026-10-10"]["orders"], 1)
        self.assertEqual(set(days["2026-10-11"]["products"]), {10, "set:Keto set"})
        self.assertEqual(days["2026-10-11"]["products"][10]["revenue"], 150_000)
        self.assertEqual(days["2026-10-10"]["new_users"], 1)     # 18:59 UTC = 23:59
        self.assertEqual(days["2026-10-11"]["ad_users"], 1)      # 19:00 UTC = 00:00
        self.assertIn(40, out["catalog"])
        orders_sql = next(q for q in conn.queries if "FROM orders" in q)
        self.assertIn(database.SALE_SQL, orders_sql)
        self.assertIn("<> 'b2b'", orders_sql)
        self.assertIn("source = 'manual' OR user_id <> ALL", orders_sql)


class ReportTest(unittest.TestCase):
    def test_report_survives_a_database_failure(self):
        rows = [{"spend": "10", "impressions": "1000", "reach": "800",
                 "date_start": "2026-10-12", "date_stop": "2026-10-12"}]
        with patch.object(meta_ads, "fetch_insights", AsyncMock(return_value=rows)), \
             patch.object(database, "get_sales_daily", AsyncMock(side_effect=RuntimeError("db"))):
            with self.assertLogs("meta_ads", "ERROR"):
                text = asyncio.run(meta_ads.build_report("today"))
        self.assertIn("Sarflandi", text)
        self.assertNotIn("Sotuvga ta'siri", text)

    def test_report_includes_sales_block(self):
        rows = [{"spend": "10", "impressions": "1000", "reach": "800",
                 "date_start": "2026-10-05", "date_stop": "2026-10-11"}]
        sales = {"days": {"2026-10-06": {"orders": 3, "revenue": 300_000.0, "new_users": 4,
                                         "ad_users": 0, "products": {}}}, "catalog": {}}
        with patch.object(meta_ads, "fetch_insights", AsyncMock(return_value=rows)), \
             patch.object(database, "get_sales_daily", AsyncMock(return_value=sales)), \
             patch.object(ads_impact, "_usd_rate", AsyncMock(return_value=12_000.0)):
            text = asyncio.run(meta_ads.build_report("last_7d"))
        self.assertIn("Sotuvga ta'siri</b> · 05.10–11.10", text)
        self.assertIn("Buyurtmalar: <b>3</b>", text)


if __name__ == "__main__":
    unittest.main()
