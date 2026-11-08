"""Reklama kampaniyalari ↔ bot hisobi (egasining TZ'si, 2026-11-08). Meta
mock — hech qanday haqiqiy so'rov yuborilmaydi; Graph javoblarining shakli
08.11 dagi haqiqiy javoblardan olingan."""
import asyncio
import json
import os
import unittest
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")
os.environ.setdefault("ADMIN_WEB_PASSWORD", "test-password")

import ad_campaigns as ac
import database
import meta_ads
import shop_links

TABLE = [{"campaign_id": "120261009449570456", "name": "Kepak", "start_code": "kepak", "emoji": "🥖", "manual": True},
         {"campaign_id": "120261022820980456", "name": "Glyuten 1-qism", "start_code": "gluten_1_qism", "emoji": "🌾",
          "manual": True}]
ROWS = [  # Graph level=campaign, the TZ's sample numbers
    {"campaign_id": "120261009449570456", "campaign_name": "[07/11/2026] Kepak - Trafik (bot do'kon)",
     "spend": "4.90", "impressions": "7252", "inline_link_clicks": "408", "cost_per_inline_link_click": "0.012",
     "date_start": "2026-11-08", "date_stop": "2026-11-08"},
    {"campaign_id": "120261022820980456", "campaign_name": "[08/11/2026] Glyuten 1-qism - Trafik (bot do'kon)",
     "spend": "3.52", "impressions": "8897", "inline_link_clicks": "580", "cost_per_inline_link_click": "0.006",
     "date_start": "2026-11-08", "date_stop": "2026-11-08"},
    {"campaign_id": "999", "campaign_name": "Instagram post: yangi video", "spend": "1.00", "impressions": "500",
     "inline_link_clicks": "10", "date_start": "2026-11-08", "date_stop": "2026-11-08"},
    {"campaign_id": "120260996367650456", "campaign_name": "[06/11/2026] KETO SHOP bot", "spend": "0",
     "impressions": "1", "inline_link_clicks": "0"},
]
COUNTS = {"kepak": {"bot": 120, "app": 85}, "gluten_1_qism": {"bot": 210, "app": 140}}


def run(coro):
    return asyncio.run(coro)


def report(rows=ROWS, counts=COUNTS):
    items, totals = ac.summarize(rows, TABLE, counts)
    return ac.format_report({"label": "bugun", "first": date(2026, 11, 8), "last": date(2026, 11, 8),
                             "day_starts": 13, "items": items, "totals": totals})


class ReportTest(unittest.TestCase):
    def test_the_owners_layout(self):
        text = report()
        self.assertIn("📊 <b>Reklama — bugun (08.11)</b>", text)
        self.assertIn("13:00 da boshlanadi", text)
        self.assertIn("🥖 <b>Kepak</b>\n💰 $4.90 · 👁 7 252 · 👆 408 bosish ($0.012)\n"
                      "🤖 botga 120 · 🛍 do'konga 85\n➡️ 1 START narxi: $0.041", text)
        self.assertIn("🌾 <b>Glyuten 1-qism</b>\n💰 $3.52 · 👁 8 897 · 👆 580 bosish ($0.006)\n"
                      "🤖 botga 210 · 🛍 do'konga 140\n➡️ 1 START narxi: $0.017", text)
        self.assertIn("<b>Jami:</b> $9.42 · botga 330 · do'konga 225", text)

    def test_a_new_campaign_shows_by_itself(self):
        text = report()
        self.assertIn("📣 <b>Instagram post: yangi video</b>", text)
        self.assertIn("/reklama_bog 999 kod", text)
        self.assertNotIn("KETO SHOP bot", text)                 # an old row with no spend stays out

    def test_shop_link_ads_are_priced_per_opening(self):
        text = report(counts={"kepak": {"bot": 0, "app": 50}, "gluten_1_qism": {"bot": 0, "app": 0}})
        self.assertIn("➡️ 1 do'kon ochilishi narxi: $0.098", text)
        self.assertIn("➡️ 1 START narxi: —", text)

    def test_quiet_period(self):
        self.assertIn("reklama yurmagan", report(rows=[], counts={}))


class LinkReadingTest(unittest.TestCase):
    def test_code_from_the_ad_button(self):
        ad = {"creative": {"object_story_spec": {"video_data": {"call_to_action": {
            "type": "SHOP_NOW", "value": {"link": "https://t.me/ketoshopbot?start=kepak"}}}}}}
        self.assertEqual(ac.code_from_link(ac.ad_link(ad)), "kepak")
        self.assertEqual(ac.code_from_link("https://t.me/ketoshopbot/shop?startapp=gluten-1-qism"), "gluten_1_qism")
        for url in (None, "", "http://fb.me/", "https://ketoshop.uz/?start=x", "https://t.me/ketoshopbot"):
            self.assertIsNone(ac.code_from_link(url), url)
        self.assertIsNone(ac.ad_link({"creative": {"id": "1"}}))           # built on an existing post

    def test_clean_campaign_names(self):
        self.assertEqual(ac.clean_name("[08/11/2026] Glyuten 1-qism - Trafik (bot do'kon)"), "Glyuten 1-qism")
        self.assertEqual(ac.clean_name("Keto video 1 (Eritritol 1)"), "Keto video 1 (Eritritol 1)")

    def test_sync_links_new_campaigns_and_never_overrides(self):
        ads = {"data": [
            {"campaign_id": "555", "campaign": {"name": "[09/11/2026] Chia - Trafik"},
             "creative": {"object_story_spec": {"link_data": {"link": "https://t.me/ketoshopbot?start=chia"}}}},
            {"campaign_id": "120261009449570456", "campaign": {"name": "x"},
             "creative": {"object_story_spec": {"link_data": {"link": "https://t.me/ketoshopbot?start=boshqa"}}}},
            {"campaign_id": "777", "creative": {"object_story_spec": {"link_data": {"link": "https://t.me/ketoshopbot?start=sayt"}}}},
        ]}
        ensure_code, set_link = AsyncMock(return_value=True), AsyncMock()
        with patch.object(meta_ads, "account_ids", AsyncMock(return_value=["840216037679254"])), \
             patch.object(meta_ads, "_get", AsyncMock(return_value=ads)), \
             patch.object(ac, "links", AsyncMock(return_value=TABLE)), \
             patch.object(ac, "set_link", set_link), \
             patch.object(shop_links, "ensure_code", ensure_code):
            self.assertEqual(run(ac.sync_from_ads(object(), force=True)), 1)
        ensure_code.assert_awaited_once_with("chia", "Chia")
        set_link.assert_awaited_once_with("555", "chia", "Chia", manual=False)


class ScheduleTest(unittest.TestCase):
    def test_daily_report_after_the_account_day_closes(self):
        # Los Angeles is UTC-8 in winter: its 09.11 starts at 08:00 UTC = 13:00 Tashkent.
        self.assertIsNone(ac.daily_due(datetime(2026, 11, 9, 8, 4), -8))
        self.assertEqual(ac.daily_due(datetime(2026, 11, 9, 8, 5), -8), date(2026, 11, 9))
        self.assertEqual(ac.meta_day_start_tashkent(-8), 13)
        self.assertEqual(ac.meta_day_start_tashkent(-7), 12)              # summer time

    def test_zero_spend_needs_three_quiet_hours(self):
        t0 = datetime(2026, 11, 9, 10, 0)
        hist = [(t0, 1.20), (datetime(2026, 11, 9, 11, 0), 1.20), (datetime(2026, 11, 9, 12, 30), 1.20)]
        self.assertFalse(ac.zero_spend_since(hist, datetime(2026, 11, 9, 12, 30)))   # 2.5 h only
        hist.append((datetime(2026, 11, 9, 13, 1), 1.20))
        self.assertTrue(ac.zero_spend_since(hist, datetime(2026, 11, 9, 13, 1)))
        hist.append((datetime(2026, 11, 9, 13, 6), 1.31))
        self.assertFalse(ac.zero_spend_since(hist, datetime(2026, 11, 9, 13, 6)))    # it moved

    def test_period_words(self):
        p = meta_ads.preset_from_args
        self.assertEqual(p("/reklama"), "today")
        self.assertEqual(p("/reklama kecha"), "yesterday")
        self.assertEqual(p("/reklama 7"), "last_7d")
        self.assertEqual(p("/reklama 30"), "last_30d")
        self.assertIsNone(p("/reklama qachondir"))


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class TickTest(unittest.TestCase):
    def tick(self, ads, today_rows, counts, claimed=True, now=datetime(2026, 11, 9, 6, 0)):
        bot = MagicMock()
        bot.send_message = AsyncMock()
        claims = []

        async def claim(key):
            claims.append(key)
            return claimed

        class FakeDT(datetime):
            @classmethod
            def now(cls, tz=None):
                return now.replace(tzinfo=tz) if tz else now

        ac._last_status_check = None
        ac._spend_hist.clear()
        with patch.object(ac.aiohttp, "ClientSession", _Session), \
             patch.object(ac, "datetime", FakeDT), \
             patch("ads_impact.account_tz_hours", AsyncMock(return_value=-8)), \
             patch.object(ac, "sync_from_ads", AsyncMock(return_value=0)), \
             patch.object(meta_ads, "fetch_ads_status", AsyncMock(return_value=ads)), \
             patch.object(ac, "fetch_rows", AsyncMock(return_value=today_rows)), \
             patch.object(ac, "links", AsyncMock(return_value=TABLE)), \
             patch.object(ac, "build_report", AsyncMock(return_value="REPORT")), \
             patch.object(shop_links, "people_between", AsyncMock(return_value=counts)), \
             patch.object(database, "claim_release_notes", claim), \
             patch.object(ac, "ADMIN_IDS", [1]):
            run(ac.tick(bot))
        return [c.args[1] for c in bot.send_message.await_args_list], claims

    def test_disapproved_ad_and_expensive_start(self):
        ads = [{"id": "a1", "campaign_id": "120261009449570456", "name": "Kepak video", "effective_status": "DISAPPROVED",
                "issues_info": [{"error_message": "Reklama qoidalariga zid"}]}]
        rows = [{"campaign_id": "120261009449570456", "spend": "5.37"}]
        sent, claims = self.tick(ads, rows, {"kepak": {"bot": 10, "app": 3}, "gluten_1_qism": {"bot": 0, "app": 0}})
        self.assertTrue(any("DISAPPROVED" in t and "qoidalariga zid" in t for t in sent))
        self.assertTrue(any("qimmatga" in t and "$0.537" in t for t in sent))     # 5.37 / 10 > $0.10
        self.assertIn("adalert:a1:DISAPPROVED", claims)
        self.assertTrue(any(k.startswith("adcost:120261009449570456:") for k in claims))

    def test_cheap_start_and_small_spend_stay_quiet(self):
        rows = [{"campaign_id": "120261009449570456", "spend": "4.90"},
                {"campaign_id": "120261022820980456", "spend": "0.40"}]
        sent, claims = self.tick([], rows, {"kepak": {"bot": 120, "app": 85}, "gluten_1_qism": {"bot": 0, "app": 0}})
        self.assertFalse([t for t in sent if "qimmatga" in t])
        self.assertFalse([k for k in claims if k.startswith("adcost")])

    def test_daily_report_once_per_account_day(self):
        sent, claims = self.tick([], [], {}, now=datetime(2026, 11, 9, 8, 6))
        self.assertIn("ads-daily:2026-11-09", claims)
        self.assertIn("REPORT", sent)
        sent, _ = self.tick([], [], {}, claimed=False, now=datetime(2026, 11, 9, 8, 30))
        self.assertNotIn("REPORT", sent)

    def test_meta_trouble_never_raises(self):
        with patch.object(ac.aiohttp, "ClientSession", side_effect=RuntimeError("network")):
            run(ac.tick(MagicMock()))


class WiringTest(unittest.TestCase):
    def test_admin_panel_button_and_command(self):
        import keyboards
        kb = keyboards.admin_stats_menu_keyboard("uz")
        self.assertIn("ads:today", [b.callback_data for row in kb.inline_keyboard for b in row])
        src = open(keyboards.__file__, encoding="utf-8").read()
        self.assertIn('command="reklama_bog"', src)

    def test_admin_api(self):
        import admin_web
        from aiohttp.test_utils import make_mocked_request
        data = {"preset": "today", "label": "bugun", "first": date(2026, 11, 8), "last": date(2026, 11, 8),
                "tz_hours": -8, "day_starts": 13, "items": [], "totals": {"spend": 0}}
        with patch.object(admin_web, "ADMIN_WEB_PASSWORD", "test"), \
             patch.object(admin_web, "_authed", return_value=True), \
             patch.object(meta_ads, "is_enabled", return_value=True), \
             patch.object(ac, "collect", AsyncMock(return_value=data)) as collect:
            resp = run(admin_web.api_ads_campaigns(make_mocked_request("GET", "/admin/api/ads/campaigns?period=yesterday")))
        body = json.loads(resp.text)
        self.assertEqual((body["enabled"], body["first"], body["day_starts"]), (True, "2026-11-08", 13))
        collect.assert_awaited_once_with("yesterday")
        with patch.object(admin_web, "ADMIN_WEB_PASSWORD", "test"):     # the panel is switched on
            resp = run(admin_web.api_ads_campaigns(make_mocked_request("GET", "/admin/api/ads/campaigns")))
        self.assertEqual(resp.status, 401)

    def test_dashboard_and_tab(self):
        page = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webapp", "admin.html"),
                    encoding="utf-8").read()
        self.assertIn('id="adStripKpis"', page)
        self.assertIn("loadAdStrip();", page)
        self.assertIn('id="adsCampRows"', page)
        self.assertIn("loadAdsCampaigns(),loadAdsMain()", page)
        self.assertIn("/admin/api/ads/campaigns?period=", page)


if __name__ == "__main__":
    unittest.main()
