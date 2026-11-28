"""Ishonchli manbalardan javob (trusted_sources.py, egasi 2026-11-28)."""
import asyncio
import os
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import ai_sales
import comment_ai
import trusted_sources as ts


def fake_openai(text, annotations=()):
    resp = NS(output_text=text, usage=None,
              output=[NS(content=[NS(annotations=[NS(url=u, title=t) for t, u in annotations])])])
    client = MagicMock()
    client.responses.create = AsyncMock(return_value=resp)
    return client


class LookupTest(unittest.TestCase):
    def setUp(self):
        ts._cache.clear()

    def _run(self, client, q="eritritol diabetga zararlimi"):
        with patch.object(comment_ai, "_openai_key", AsyncMock(return_value="k")), \
                patch("openai.AsyncOpenAI", return_value=client):
            return asyncio.run(ts.lookup(q))

    def test_search_is_limited_to_trusted_domains_and_cached(self):
        client = fake_openai("Eritritol qon shakarini oshirmaydi.\nManba: FDA — https://www.fda.gov/x")
        out = self._run(client)
        self.assertIn("Manba: FDA", out)
        tool = client.responses.create.await_args.kwargs["tools"][0]
        self.assertEqual(tool["type"], "web_search")
        self.assertIn("fda.gov", tool["filters"]["allowed_domains"])
        self.assertIn("efsa.europa.eu", tool["filters"]["allowed_domains"])
        self._run(client)                                         # bir xil savol — keshdan
        self.assertEqual(client.responses.create.await_count, 1)

    def test_citation_from_annotations_when_text_has_none(self):
        client = fake_openai("Steviya kuniga 4 mg/kg gacha xavfsiz deb topilgan.",
                             [("EFSA stevia", "https://www.efsa.europa.eu/s")])
        out = self._run(client, "steviya kuniga qancha")
        self.assertIn("Manba: EFSA stevia — https://www.efsa.europa.eu/s", out)

    def test_not_found_or_error_is_empty(self):
        self.assertEqual(self._run(fake_openai("TOPILMADI"), "q1"), "")
        bad = MagicMock()
        bad.responses.create = AsyncMock(side_effect=RuntimeError("net"))
        self.assertEqual(self._run(bad, "q2"), "")


class ToolTest(unittest.TestCase):
    def test_tool_registered_and_dispatched(self):
        spec = next(t for t in ai_sales._TOOL_SPECS if t["name"] == "ishonchli_manba")
        self.assertEqual(spec["input_schema"]["required"], ["savol"])
        self.assertIn("ISHONCHLI MANBA", ai_sales._sales_rules())
        msg = NS(from_user=NS(id=1), chat=NS(id=1))
        with patch.object(ts, "lookup", AsyncMock(return_value="X xavfsiz.\nManba: WHO — https://who.int/a")):
            out = asyncio.run(ai_sales._run_tool(None, msg, "ishonchli_manba", {"savol": "steviya"}))
        self.assertIn("Manba: WHO", out)
        with patch.object(ts, "lookup", AsyncMock(return_value="")):
            out = asyncio.run(ai_sales._run_tool(None, msg, "ishonchli_manba", {"savol": "steviya"}))
        self.assertIn("topilmadi", out)


if __name__ == "__main__":
    unittest.main()
