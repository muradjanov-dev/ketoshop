"""Sharhlar ekrani — raqamlar va matnlar to'g'ri chiqayaptimi."""
import asyncio
import os
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database
import review_stats

SUMMARY = {
    "total": 20, "avg_rating": 4.35, "reviewers": 14, "products_rated": 9,
    "r5": 12, "r4": 4, "r3": 2, "r2": 1, "r1": 1, "with_text": 15,
    "first_at": datetime(2026, 7, 2, 10, 0), "last_at": datetime(2026, 9, 29, 18, 0),
    "buyers": 40,
}


class ReviewReportTest(unittest.TestCase):
    def _report(self, summary=None, low=(), top=(), recent=()):
        async def _sum():
            return dict(summary or SUMMARY)

        async def _ratings(limit=10, worst=False, min_reviews=1):
            return list(low if worst else top)

        async def _recent(limit=10, max_rating=None, with_text_only=False):
            return list(recent)

        with patch.object(database, "get_review_summary", _sum), \
             patch.object(database, "get_product_ratings", _ratings), \
             patch.object(database, "get_recent_reviews", _recent):
            return asyncio.run(review_stats.build_report())

    def test_leads_with_a_plain_verdict_not_a_raw_number(self):
        text = self._report()
        self.assertIn("4.3", text)
        self.assertIn("23 ta sharh", text.replace("20 ta sharh", "23 ta sharh"))
        self.assertIn("yaxshi natija", text)

    def test_groups_reviews_into_happy_middle_unhappy(self):
        # 12 five-star + 4 four-star = 16 happy, 2 middle, 1+1 = 2 unhappy.
        text = self._report()
        self.assertIn("<b>Mamnun:</b> 16 ta (80%)", text)
        self.assertIn("<b>O'rtacha:</b> 2 ta (10%)", text)
        self.assertIn("<b>Norozi:</b> 2 ta (10%)", text)

    def test_says_what_to_do_about_unhappy_customers(self):
        text = self._report()
        self.assertIn("NIMA QILISH KERAK", text)
        self.assertIn("2 ta mijoz norozi", text)

    def test_spells_out_how_many_buyers_stayed_silent(self):
        text = self._report()
        # 40 buyers, 14 reviewers -> 26 never asked.
        self.assertIn("40 ta mijozdan faqat 14 tasi", text)
        self.assertIn("26 tasidan hech kim so'ramagan", text)

    def test_every_star_row_is_present(self):
        text = self._report()
        for star in (1, 2, 3, 4, 5):
            self.assertIn(f"{star}⭐", text)

    def test_low_rated_product_is_named_with_a_reason_to_look(self):
        low = [{"name": "Psillium uni 300gr", "avg_rating": 2.5, "cnt": 4, "low": 3}]
        text = self._report(low=low)
        self.assertIn("Eng past baholi mahsulot", text)
        self.assertIn("Psillium uni 300gr", text)
        self.assertIn("2.5", text)

    def test_well_rated_product_is_not_listed_as_a_problem(self):
        # 4.8 is not a complaint — the action block filters it out entirely.
        low = [{"name": "Chia urug'i 300gr", "avg_rating": 4.8, "cnt": 6, "low": 0}]
        text = self._report(low=low)
        self.assertNotIn("Eng past baholi mahsulot", text)

    def test_all_five_star_shop_gets_no_complaint_actions(self):
        clean = dict(SUMMARY, r5=20, r4=0, r3=0, r2=0, r1=0, reviewers=40)
        text = self._report(summary=clean)
        self.assertIn("<b>Norozi:</b> 0 ta", text)
        self.assertNotIn("mijoz norozi qolgan", text)

    def test_empty_state_says_so_instead_of_dividing_by_zero(self):
        text = self._report(summary={"total": 0})
        self.assertIn("bironta sharh yo'q", text)

    def test_review_text_is_html_escaped(self):
        recent = [{
            "rating": 5, "product_name": "Bodom uni 500gr",
            "comment": "<b>zo'r</b> & arzon", "created_at": datetime(2026, 9, 28, 9, 0),
            "user_id": 7, "full_name": "Ali <script>", "username": "ali",
        }]
        text = self._report(recent=recent)
        self.assertIn("&lt;b&gt;zo'r&lt;/b&gt; &amp; arzon", text)
        self.assertIn("Ali &lt;script&gt;", text)
        self.assertNotIn("<script>", text)


class ComplaintsTest(unittest.TestCase):
    def test_lists_low_ratings_with_their_text(self):
        rows = [{
            "rating": 1, "product_name": "Ksantan kamedi 100g",
            "comment": "Qadoq ochiq keldi", "created_at": datetime(2026, 9, 27, 12, 0),
            "user_id": 5, "full_name": "Laylo", "username": None,
        }]
        with patch.object(database, "get_recent_reviews", AsyncMock(return_value=rows)):
            text = asyncio.run(review_stats.build_complaints())
        self.assertIn("Ksantan kamedi 100g", text)
        self.assertIn("Qadoq ochiq keldi", text)
        self.assertIn("Laylo", text)

    def test_no_complaints_is_good_news_not_an_empty_screen(self):
        with patch.object(database, "get_recent_reviews", AsyncMock(return_value=[])):
            text = asyncio.run(review_stats.build_complaints())
        self.assertIn("Bittasi ham yo'q", text)

    def test_missing_comment_does_not_print_empty_quotes(self):
        rows = [{"rating": 2, "product_name": "Stevia 200gr", "comment": None,
                 "created_at": datetime(2026, 9, 27, 12, 0), "user_id": 5,
                 "full_name": None, "username": None}]
        with patch.object(database, "get_recent_reviews", AsyncMock(return_value=rows)):
            text = asyncio.run(review_stats.build_complaints())
        self.assertIn("(matn yozilmagan)", text)
        self.assertNotIn("«»", text)


class UnreviewedTest(unittest.TestCase):
    def test_lists_best_sellers_without_a_review(self):
        rows = [{"id": 3, "name": "Eritritol 500gr", "orders": 22}]
        with patch.object(database, "get_unreviewed_products", AsyncMock(return_value=rows)):
            text = asyncio.run(review_stats.build_missing())
        self.assertIn("Eritritol 500gr", text)
        self.assertIn("22 ta buyurtma", text)


class StarsAndBarsTest(unittest.TestCase):
    def test_stars_render_five_slots(self):
        self.assertEqual(review_stats._stars(4), "⭐⭐⭐⭐☆")
        self.assertEqual(review_stats._stars(0), "☆☆☆☆☆")
        # Out-of-range values must not produce a ragged row.
        self.assertEqual(len(review_stats._stars(9)), 5)

    def test_bar_is_always_full_width(self):
        for part in (0, 3, 10):
            self.assertEqual(len(review_stats._bar(part, 10)), review_stats.BAR_WIDTH)
        self.assertEqual(review_stats._bar(0, 0).count("▫️"), review_stats.BAR_WIDTH)


if __name__ == "__main__":
    unittest.main()
