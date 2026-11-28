"""AI sarfi: kesh kalitlari, qisqa izohlar, kunlik sarf (egasi, 2026-11-28)."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import ai_provider
import comment_ai


class CacheKeyTest(unittest.TestCase):
    def test_sales_provider_sends_cache_key(self):
        prov = ai_provider.OpenAIProvider.__new__(ai_provider.OpenAIProvider)
        prov.model, prov.effort = "gpt-6.1-terra", "low"
        resp = MagicMock(id="r1", output=[], output_text="salom", usage=None, status="completed")
        client = MagicMock()
        client.responses.create = AsyncMock(return_value=resp)
        prov._get_client = lambda: client
        asyncio.run(prov.step({}, "QOIDALAR", "KATALOG", [], user="salom"))
        self.assertEqual(client.responses.create.await_args.kwargs["prompt_cache_key"], "ketoshop-sotuv")

    def test_comment_calls_send_cache_key(self):
        src = open(comment_ai.__file__, encoding="utf-8").read()
        self.assertIn('prompt_cache_key="ketoshop-izoh"', src)
        import ig_direct
        self.assertIn('prompt_cache_key="ketoshop-direct"', open(ig_direct.__file__, encoding="utf-8").read())


class ShortTest(unittest.TestCase):
    def test_short_rule_and_fewer_double_calls(self):
        self.assertIn("odatda 1–2 qisqa gap, 200 belgigacha", comment_ai.RULES)
        self.assertNotIn("boshqa", comment_ai.COMPLEX)
        self.assertEqual(comment_ai.COMPLEX, {"salomatlik", "shikoyat"})


if __name__ == "__main__":
    unittest.main()
