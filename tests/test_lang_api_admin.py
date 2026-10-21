"""GET /api/lang tells the Mini App whether the viewer is an admin — admins
hear the birdsong at night too, so they can test it."""
import asyncio
import json
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import webapp_server


class Req(dict):
    pass


def call(user_id, lang="uz"):
    resp = asyncio.run(webapp_server.api_get_lang(Req(user_id=user_id, user_lang=lang)))
    return json.loads(resp.text)


class LangApiTest(unittest.TestCase):
    def test_admin_flag(self):
        admin = next(iter(webapp_server.ADMIN_IDS)) if webapp_server.ADMIN_IDS else None
        if admin is not None:
            self.assertEqual(call(admin), {"lang": "uz", "is_admin": True})
        self.assertEqual(call(999_000_111, "ru"), {"lang": "ru", "is_admin": False})


if __name__ == "__main__":
    unittest.main()
