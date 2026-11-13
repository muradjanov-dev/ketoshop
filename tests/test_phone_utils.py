"""Telefon raqami — xaridor qanday yozsa ham (2026-10-21). Mini App'da
«Buyurtmani tasdiqlash» ko'p odamda «ishlamagan»: raqam "+998…" ko'rinishida
bo'lmasa rad etilib, xato ekrandan tashqarida chiqqan. Bazaga ulanmaydi.

2026-11-11: hali ham 45 checkoutdan 18 tasida telefon xatosi. Endi arab /
fors / keng raqamlar, "+998 +998 …" autofill, ko'rinmas belgilar ham olinadi;
xato aniq aytiladi (bo'sh / qisqa / uzun / chet el / operator kodi), maydon
oldingi buyurtmadagi raqam bilan to'ldiriladi."""
import asyncio
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

from aiohttp.test_utils import make_mocked_request

import database
import webapp_server
from phone_utils import format_uz_phone, normalize_uz_phone

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "webapp" / "index.html").read_text(encoding="utf-8").replace("\r\n", "\n")

GOOD = {
    "+998901234567": "+998901234567",
    "+998 90 123 45 67": "+998901234567",
    "+998 (90) 123-45-67": "+998901234567",
    "998901234567": "+998901234567",            # Telegram's shared contact has no "+"
    "90 123 45 67": "+998901234567",
    "901234567": "+998901234567",
    "(90) 123-45-67": "+998901234567",
    "8 90 123 45 67": "+998901234567",
    "8 (88) 123-45-67": "+998881234567",
    "88 123 45 67": "+998881234567",
    "00998901234567": "+998901234567",
    " 33 444 55 66 ": "+998334445566",
    "+998.97.765.43.21": "+998977654321",
    "Tel: 90-123-45-67": "+998901234567",
    # autofill after the buyer had typed "+998"
    "+998 +998 90 123 45 67": "+998901234567",
    "998998901234567": "+998901234567",
    # copied from a phone's contacts: bidi marks, no-break spaces and hyphens
    "‪+998 90 123‑45‑67‬": "+998901234567",
    "​90 123 45 67​": "+998901234567",
    # Arabic-Indic, Persian and full-width keyboards
    "٩٩٨٩٠١٢٣٤٥٦٧": "+998901234567",
    "۹۰ ۱۲۳ ۴۵ ۶۷": "+998901234567",
    "９０１２３４５６７": "+998901234567",
}
# raw → what the Mini App tells the buyer is wrong with it
BAD = {
    "": "empty",
    "abc": "empty",
    "12345": "short",
    "90123456": "short",
    "+99890123456": "short",
    "+998 90 123 45 6": "short",
    "٩٠": "short",
    "9989012345678": "long",
    "9012345678": "long",
    "90 123 45 67, 93 765 43 21": "long",
    "+7 916 123 45 67": "foreign",
    "79161234567": "foreign",
    "+1 202 555 0123": "foreign",
    "123456789": "code",
    "+998 12 345 67 89": "code",
    "012345678": "code",
}


class NormalizeTest(unittest.TestCase):
    def test_every_common_spelling(self):
        for raw, want in GOOD.items():
            self.assertEqual(normalize_uz_phone(raw), want, repr(raw))

    def test_not_an_uzbek_number(self):
        for raw in list(BAD) + [None, 901234567]:
            self.assertIsNone(normalize_uz_phone(raw), repr(raw))

    def test_only_ascii_digits_are_stored(self):
        for raw in GOOD:
            self.assertRegex(normalize_uz_phone(raw), r"^\+998[0-9]{9}$")

    def test_shown_with_spaces(self):
        self.assertEqual(format_uz_phone("901234567"), "+998 90 123 45 67")
        self.assertEqual(format_uz_phone("+998881234567"), "+998 88 123 45 67")
        self.assertEqual(format_uz_phone("12345"), "12345")
        self.assertEqual(format_uz_phone(None), "")


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
        self.assertEqual(self.checkout("+998 +998 90 123 45 67"), "invalid_location")
        self.assertEqual(self.checkout("٩٠ ١٢٣ ٤٥ ٦٧"), "invalid_location")

    def test_a_wrong_number_is_still_refused(self):
        self.assertEqual(self.checkout("12345"), "invalid_phone")
        self.assertEqual(self.checkout(""), "invalid_phone")
        self.assertEqual(self.checkout("123456789"), "invalid_phone")


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False
        return Ctx()


class KnownPhoneTest(unittest.TestCase):
    """The checkout field is filled from the buyer's own data."""

    def known(self, order_phones, own_phone):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[{"phone": p} for p in order_phones])
        conn.fetchval = AsyncMock(return_value=own_phone)
        with patch.object(database, "pool", FakePool(conn)):
            phone = asyncio.run(database.get_checkout_phone(77))
        sql = conn.fetch.await_args.args[0]
        self.assertIn("NOT IN ('manual', 'b2b', 'test')", sql)   # admins' orders carry someone else's number
        self.assertIn("ORDER BY created_at DESC", sql)
        return phone

    def test_latest_order_first(self):
        self.assertEqual(self.known(["90 123 45 67", "+998 93 111 22 33"], "+998944445566"), "+998901234567")

    def test_skips_a_number_the_checkout_would_refuse(self):
        self.assertEqual(self.known(["+7 916 123 45 67"], "998944445566"), "+998944445566")

    def test_nothing_known(self):
        self.assertIsNone(self.known([], None))

    def test_endpoint_answers_formatted_or_empty(self):
        async def go(value):
            req = make_mocked_request("GET", "/api/checkout/phone")
            req["user_id"] = 77
            with patch.object(database, "get_checkout_phone", AsyncMock(return_value=value)):
                resp = await webapp_server.api_checkout_phone(req)
            return json.loads(resp.body)
        self.assertEqual(asyncio.run(go("+998901234567")), {"phone": "+998 90 123 45 67"})
        self.assertEqual(asyncio.run(go(None)), {"phone": ""})

    def test_endpoint_survives_a_database_error(self):
        async def go():
            req = make_mocked_request("GET", "/api/checkout/phone")
            req["user_id"] = 77
            with patch.object(database, "get_checkout_phone", AsyncMock(side_effect=RuntimeError("db down"))):
                resp = await webapp_server.api_checkout_phone(req)
            return json.loads(resp.body)
        with self.assertLogs(webapp_server.logger, "ERROR"):
            self.assertEqual(asyncio.run(go()), {"phone": ""})


class MiniAppWiringTest(unittest.TestCase):
    def test_route_and_prefill(self):
        self.assertIn('add_get("/api/checkout/phone", api_checkout_phone)',
                      (ROOT / "webapp_server.py").read_text(encoding="utf-8"))
        render = PAGE[PAGE.index("function renderCheckoutPage("):PAGE.index("async function initKetoRedeemUI(")]
        self.assertIn("prefillCheckoutPhone();", render)
        self.assertIn("api('/api/checkout/phone')", PAGE)

    def test_field_tells_what_is_wrong_and_keeps_the_number(self):
        submit = PAGE[PAGE.index("async function submitOrder("):PAGE.index("// ===== CHEQUE UPLOAD =====")]
        self.assertIn("showCheckoutFieldError('inp-phone', phoneProblemText(problem), true);", submit)
        self.assertIn("Trk.ev('checkout', 'checkout', 'error:phone', problem)", submit)
        self.assertNotIn("document.getElementById('inp-phone').value = '';", submit)
        self.assertIn('<div class="phone-hint" id="phone-hint"', PAGE)
        self.assertIn('placeholder="90 123 45 67"', PAGE)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class MiniAppPhoneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        numbers = list(GOOD) + list(BAD)
        out = subprocess.run(["node", str(ROOT / "tests" / "phone_check.js"), json.dumps(numbers)],
                             capture_output=True, text=True, check=True, cwd=ROOT, encoding="utf-8").stdout
        cls.result = json.loads(out)
        cls.numbers = numbers

    def test_same_rule_as_the_server(self):
        for raw, got in zip(self.numbers, self.result["normalized"]):
            self.assertEqual(got, normalize_uz_phone(raw), repr(raw))

    def test_same_display_as_the_server(self):
        for raw, got in zip(self.numbers, self.result["formatted"]):
            self.assertEqual(got, format_uz_phone(raw) if raw else "", repr(raw))

    def test_says_what_is_wrong(self):
        for raw, got in zip(self.numbers, self.result["problems"]):
            self.assertEqual(got, BAD.get(raw), repr(raw))

    def test_the_error_is_brought_into_view(self):
        calls = self.result["calls"]
        kinds = [c[0] for c in calls]
        self.assertIn(["after", "checkout-error", "Telefon raqamini tekshiring"], calls)
        # The phone's whole box to the top — the keyboard opens below it.
        self.assertIn(["scroll", "box", "start"], calls)
        self.assertIn("focus", kinds)
        self.assertIn(["toast", "Telefon raqamini tekshiring", True], calls)
        self.assertIn(["haptic", "error"], calls)


if __name__ == "__main__":
    unittest.main()
