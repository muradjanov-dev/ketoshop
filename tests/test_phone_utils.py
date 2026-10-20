"""Telefon raqami — xaridor qanday yozsa ham (2026-10-21). Mini App'da
«Buyurtmani tasdiqlash» ko'p odamda «ishlamagan»: raqam "+998…" ko'rinishida
bo'lmasa rad etilib, xato ekrandan tashqarida chiqqan. Bazaga ulanmaydi."""
import asyncio
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

from aiohttp.test_utils import make_mocked_request

import webapp_server
from phone_utils import normalize_uz_phone

ROOT = Path(__file__).resolve().parent.parent

GOOD = {
    "+998901234567": "+998901234567",
    "+998 90 123 45 67": "+998901234567",
    "+998 (90) 123-45-67": "+998901234567",
    "998901234567": "+998901234567",
    "90 123 45 67": "+998901234567",
    "901234567": "+998901234567",
    "(90) 123-45-67": "+998901234567",
    "8 90 123 45 67": "+998901234567",
    "00998901234567": "+998901234567",
    " 33 444 55 66 ": "+998334445566",
    "+998.97.765.43.21": "+998977654321",
}
BAD = ["", "12345", "90123456", "+7 916 123 45 67", "+99890123456", "9989012345678",
       "79161234567", "abc", "+998 90 123 45 6"]


class NormalizeTest(unittest.TestCase):
    def test_every_common_spelling(self):
        for raw, want in GOOD.items():
            self.assertEqual(normalize_uz_phone(raw), want, raw)

    def test_not_an_uzbek_number(self):
        for raw in BAD + [None, 901234567]:
            self.assertIsNone(normalize_uz_phone(raw), raw)


class CheckoutApiTest(unittest.TestCase):
    def checkout(self, phone):
        async def go():
            req = make_mocked_request("POST", "/api/checkout")
            req["user_id"] = 77
            req["user_lang"] = "uz"
            # No location: the next check after the phone answers invalid_location.
            req.json = AsyncMock(return_value={"phone": phone, "payment_method": "online", "delivery_method": "bts"})
            resp = await webapp_server.api_checkout(req)
            return json.loads(resp.body)["error"]
        return asyncio.run(go())

    def test_a_local_number_passes_the_phone_check(self):
        self.assertEqual(self.checkout("90 123 45 67"), "invalid_location")
        self.assertEqual(self.checkout("+998 (90) 123-45-67"), "invalid_location")

    def test_a_wrong_number_is_still_refused(self):
        self.assertEqual(self.checkout("12345"), "invalid_phone")
        self.assertEqual(self.checkout(""), "invalid_phone")


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class MiniAppPhoneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        numbers = list(GOOD) + BAD
        out = subprocess.run(["node", str(ROOT / "tests" / "phone_check.js"), json.dumps(numbers)],
                             capture_output=True, text=True, check=True, cwd=ROOT).stdout
        cls.result = json.loads(out)
        cls.numbers = numbers

    def test_same_rule_as_the_server(self):
        for raw, got in zip(self.numbers, self.result["normalized"]):
            self.assertEqual(got, normalize_uz_phone(raw), raw)

    def test_the_error_is_brought_into_view(self):
        calls = self.result["calls"]
        kinds = [c[0] for c in calls]
        self.assertIn(["after", "checkout-error", "Telefon raqamini tekshiring"], calls)
        self.assertIn(["scroll", "center"], calls)
        self.assertIn("focus", kinds)
        self.assertIn(["toast", "Telefon raqamini tekshiring", True], calls)
        self.assertIn(["haptic", "error"], calls)


if __name__ == "__main__":
    unittest.main()
