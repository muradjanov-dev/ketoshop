"""Kuryer panelidan telefonda Yandex ilovasiga o'tish (egasi, 2026-11-02:
"saytda ochmasin").

/nav (webapp/nav.html) Yandex Navigator ilovasini barcha nuqtalar bilan
ochadi; Android'da intent:// + paket + browser_fallback_url
orqali ilova bo'lmasa — "o'rnating". Maps alohida tanlanadi; sayt faqat
pastdagi kichik havola. Skript node'da soxta brauzer bilan yuritiladi
(tests/nav_bridge_check.js).
"""
import asyncio
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

from aiohttp import web

import admin_web

ROOT = Path(__file__).resolve().parent.parent
STOPS = "41.311000,69.279000~41.326400,69.234700~41.299000,69.240000"


def _fallback(intent: str) -> str:
    return unquote(intent.split("S.browser_fallback_url=")[1].split(";end")[0])


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class NavBridgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = subprocess.run(["node", str(ROOT / "tests" / "nav_bridge_check.js")],
                             capture_output=True, text=True, encoding="utf-8", timeout=60)
        if out.returncode:
            raise AssertionError(out.stderr)
        cls.r = json.loads(out.stdout)

    def test_android_opens_navigator_with_every_stop_first(self):
        url = self.r["android1"]["nav"]["replaced"]
        self.assertTrue(url.startswith(
            "intent://build_route_on_map?lat_to=41.299000&lon_to=69.240000"
            "&lat_via_0=41.311000&lon_via_0=69.279000&lat_via_1=41.326400&lon_via_1=69.234700#Intent;"), url)
        self.assertIn(";scheme=yandexnavi;package=ru.yandex.yandexnavi;", url)
        fb = _fallback(url)
        self.assertEqual(fb, f"https://keto.test/nav?p={STOPS}&s=2")
        self.assertNotIn(";", fb)          # a ";" would split the intent URI

    def test_missing_navigator_offers_install_without_launching_another_app(self):
        r = self.r["android2"]
        self.assertIsNone(r["nav"]["replaced"])
        self.assertFalse(r["view"]["inst"]["hidden"])
        self.assertIn("id=ru.yandex.yandexnavi", r["view"]["inst"]["href"])

    def test_android_no_app_asks_to_install_not_the_website(self):
        r = self.r["android3"]
        self.assertIsNone(r["nav"]["replaced"])
        self.assertFalse(r["view"]["inst"]["hidden"])
        self.assertIn("play.google.com/store/apps/details?id=ru.yandex.yandexnavi", r["view"]["inst"]["href"])
        self.assertEqual(r["view"]["inst"]["cls"], "btn p")
        self.assertNotEqual(r["view"]["web"]["cls"], "btn p")   # the site stays a small link

    def test_ios_opens_navigator_then_offers_install_if_page_stays_visible(self):
        r = self.r["iosStay"]
        self.assertEqual(len(r["nav"]["assigned"]), 1)
        self.assertTrue(r["nav"]["assigned"][0].startswith("yandexnavi://build_route_on_map?lat_to=41.299000"))
        self.assertFalse(r["view"]["inst"]["hidden"])
        self.assertEqual(r["view"]["inst"]["href"], "https://apps.apple.com/app/id474500851")
        # the app opened (page hidden) → no further jumps, no install prompt
        left = self.r["iosLeft"]
        self.assertEqual(len(left["nav"]["assigned"]), 1)
        self.assertTrue(left["view"]["inst"]["hidden"])

    def test_computer_gets_the_website(self):
        r = self.r["pc"]
        self.assertIsNone(r["nav"]["replaced"])
        self.assertEqual(r["nav"]["assigned"], [])
        self.assertEqual(r["view"]["web"]["href"], f"https://yandex.uz/maps/?rtext=~{STOPS}&rtt=auto")
        self.assertTrue(r["view"]["maps"]["hidden"])

    def test_bad_coordinates_say_so(self):
        r = self.r["empty"]
        self.assertIsNone(r["nav"]["replaced"])
        self.assertEqual(r["view"]["ttl"]["text"], "Manzil topilmadi")

    def test_single_destination_has_no_extra_via_point(self):
        params = parse_qs(urlsplit(self.r["single"]["state"]["naviUrl"]).query)
        self.assertEqual(params, {"lat_to": ["41.311000"], "lon_to": ["69.279000"]})

    def test_all_thirty_stops_reach_navigator_in_order(self):
        params = parse_qs(urlsplit(self.r["many"]["state"]["naviUrl"]).query)
        self.assertEqual(params["lat_to"], ["41.029000"])
        self.assertEqual(params["lat_via_0"], ["41.000000"])
        self.assertEqual(params["lat_via_28"], ["41.028000"])
        self.assertEqual(len([key for key in params if key.startswith("lat_via_")]), 29)

    def test_known_origin_is_preserved_in_launch_and_fallback(self):
        params = parse_qs(urlsplit(self.r["origin"]["state"]["naviUrl"]).query)
        self.assertEqual(params.get("lat_from"), ["41.350000"])
        self.assertEqual(params.get("lon_from"), ["69.300000"])
        fb = _fallback(self.r["origin"]["nav"]["replaced"])
        self.assertEqual(parse_qs(urlsplit(fb).query)["from"], ["41.350000,69.300000"])
        self.assertEqual(self.r["originFallback"]["state"]["naviUrl"],
                         self.r["origin"]["state"]["naviUrl"])


class NavRouteTest(unittest.TestCase):
    def test_route_registered_and_page_served(self):
        app = web.Application()
        admin_web.setup_admin_routes(app)
        paths = {r.resource.canonical for r in app.router.routes() if r.method == "GET"}
        self.assertIn("/nav", paths)
        resp = asyncio.run(admin_web.nav_page(None))
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.content_type, "text/html")
        self.assertIn("yandexmaps://", resp.text)


if __name__ == "__main__":
    unittest.main()
