"""AI sinovi: eski va yangi versiya, ko'r hakam (ai_eval.py, egasi 2026-11-27)."""
import asyncio
import os
import random
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import ai_eval
import ai_sales


class UnblindTest(unittest.TestCase):
    def test_maps_back_to_old_new(self):
        self.assertEqual(ai_eval.unblind({"a": 8, "b": 5, "better": "A", "reason": "r"}, True),
                         {"new": 8, "old": 5, "better": "yangi", "reason": "r"})
        self.assertEqual(ai_eval.unblind({"a": 8, "b": 5, "better": "A", "reason": "r"}, False),
                         {"new": 5, "old": 8, "better": "eski", "reason": "r"})
        self.assertEqual(ai_eval.unblind({"a": 6, "b": 6, "better": "teng", "reason": ""}, False)["better"], "teng")


class RunTest(unittest.TestCase):
    def test_both_versions_answer_and_judge_never_sees_labels(self):
        calls = []

        async def fake_answer(client, model, instructions, q):
            calls.append((model, "ESKI" if instructions.startswith("OLD") else "YANGI"))
            return f"{model}:{q}"

        seen = []

        async def fake_judge(client, q, a, b):
            seen.append((a, b))
            return {"a": 9, "b": 4, "better": "A", "reason": "aniqroq"}

        with patch.object(ai_eval, "_client", AsyncMock(return_value=object())), \
                patch.object(ai_eval, "old_rules", return_value="OLD RULES"), \
                patch.object(ai_sales, "_sales_rules", return_value="NEW RULES"), \
                patch.object(ai_sales, "_dynamic_block", AsyncMock(return_value="KATALOG")), \
                patch.object(ai_sales, "_catalog_text", AsyncMock(return_value="")), \
                patch.object(ai_sales, "PROVIDER", NS(model="gpt-6.1-terra")), \
                patch.object(ai_eval, "answer", fake_answer), patch.object(ai_eval, "judge", fake_judge):
            res = asyncio.run(ai_eval.run(["s1", "s2", "s3", "s4"], rng=random.Random(1)))
        self.assertEqual(sorted(set(calls)), [("gpt-5.4-mini", "ESKI"), ("gpt-6.1-terra", "YANGI")])
        self.assertEqual(len(res["rows"]), 4)
        self.assertEqual(res["wins_new"] + res["wins_old"], 4)
        self.assertTrue(all("ESKI" not in a + b and "YANGI" not in a + b for a, b in seen))
        self.assertIn("🧪", ai_eval.report(res)[0])

    def test_old_rules_file_ships(self):
        text = ai_eval.old_rules()
        self.assertGreater(len(text), 5000)
        self.assertNotIn("ODAMDEK JAVOB", text)      # really the old version


if __name__ == "__main__":
    unittest.main()


class HumanRuleTest(unittest.TestCase):
    def test_answer_first_rule_in_bot_and_group(self):
        self.assertIn("ODAMDEK JAVOB", ai_sales._sales_rules())
        self.assertIn("ODAMDEK JAVOB", ai_sales._group_rules())
