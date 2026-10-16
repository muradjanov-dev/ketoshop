"""Bilim o'yinlari banki (quiz_bank.py): sayt o'yinlari va botning 2 kunlik
savoli bitta bankdan (egasi, 2026-10-16). Telegram va bazaga ulanmasdan."""
import asyncio
import json
import os
import random
import re
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import quiz_bank
import webapp_server
from translit import lat_to_cyr


class BankShapeTest(unittest.TestCase):
    def test_quiz_questions_are_complete_and_unique(self):
        self.assertGreaterEqual(len(quiz_bank.QUIZ), 50)
        ids = [x["id"] for x in quiz_bank.QUIZ]
        self.assertEqual(len(ids), len(set(ids)))
        questions = [x["q"][0] for x in quiz_bank.QUIZ]
        self.assertEqual(len(questions), len(set(questions)))
        for x in quiz_bank.QUIZ:
            self.assertEqual(len(x["a"]), 4, x["id"])
            for pair in [x["q"], x["e"], *x["a"]]:
                self.assertEqual(len(pair), 2, x["id"])
                self.assertTrue(pair[0].strip() and pair[1].strip(), x["id"])
            answers = [a[0] for a in x["a"]]
            self.assertEqual(len(answers), len(set(answers)), x["id"])

    def test_foods_and_pairs(self):
        names = [f[0] for f in quiz_bank.FOODS]
        self.assertEqual(len(names), len(set(names)))
        for f in quiz_bank.FOODS:
            self.assertEqual(len(f), 7, f[0])
            self.assertIsInstance(f[2], int)
            self.assertIsInstance(f[3], bool)
        # Both answers of "Keto mi, emas mi?" are well represented.
        self.assertGreaterEqual(sum(f[3] for f in quiz_bank.FOODS), 20)
        self.assertGreaterEqual(sum(not f[3] for f in quiz_bank.FOODS), 20)
        self.assertGreaterEqual(len(quiz_bank.PAIRS), 12)

    def test_cyrillic_has_no_latin_words_left(self):
        texts = []
        for x in quiz_bank.QUIZ:
            texts += [x["q"][0], x["e"][0], *[a[0] for a in x["a"]]]
        texts += [f[0] for f in quiz_bank.FOODS] + [f[5] for f in quiz_bank.FOODS]
        texts += [p[0][0] for p in quiz_bank.PAIRS] + [p[1][0] for p in quiz_bank.PAIRS]
        for t in texts:
            left = [w for w in re.findall(r"[A-Za-z]{2,}", lat_to_cyr(t)) if w != "MCT"]
            self.assertEqual(left, [], t)


class MiniAppTest(unittest.TestCase):
    def test_bank_json_is_script_safe_and_complete(self):
        raw = quiz_bank.bank_json()
        self.assertNotIn("</", raw)
        data = json.loads(raw)
        self.assertEqual(len(data["quiz"]), len(quiz_bank.QUIZ))
        self.assertEqual(data["quiz"][0]["a"][0], quiz_bank.QUIZ[0]["a"][0])
        self.assertEqual(len(data["foods"]), len(quiz_bank.FOODS))
        self.assertEqual(len(data["pairs"]), len(quiz_bank.PAIRS))

    def test_served_page_carries_the_bank(self):
        resp = asyncio.run(webapp_server.index(None))
        html = resp.text
        self.assertNotIn("{{GAME_BANK}}", html)
        body = re.search(r'<script type="application/json" id="game-bank">(.*?)</script>', html, re.S).group(1)
        self.assertEqual(len(json.loads(body)["quiz"]), len(quiz_bank.QUIZ))
        # The page reads the bank instead of keeping its own copy.
        self.assertIn("const GAME_QUIZ = GAME_BANK.quiz || [];", html)
        self.assertNotIn("const GAME_QUIZ = [", html)


class BotQuestionTest(unittest.TestCase):
    def test_every_key_builds(self):
        for kind, keys in quiz_bank.keys_by_kind().items():
            self.assertTrue(keys, kind)
            for key in keys[:200]:
                item = quiz_bank.build_item(key)
                self.assertIsNotNone(item, key)
                self.assertEqual(item["kind"], kind)
                self.assertIn(item["correct"], range(len(item["options"])))

    def test_keto_and_duel_answers_follow_the_numbers(self):
        honey = quiz_bank.build_item("keto:Asal")
        self.assertEqual(honey["correct"], 1)                  # "Yo'q, mos emas"
        self.assertEqual(quiz_bank.build_item("keto:Avokado")["correct"], 0)
        duel = quiz_bank.build_item("duel:Avokado|Banan")
        self.assertEqual(duel["options"][duel["correct"]][0], "Avokado")
        self.assertIn("~2 g", duel["e"][0])
        self.assertIsNone(quiz_bank.build_item("quiz:q999"))

    def test_pick_skips_sent_and_starts_over(self):
        pools = quiz_bank.keys_by_kind()
        rng = random.Random(1)
        sent = set(pools["quiz"][:-1]) | set(pools["keto"]) | set(pools["duel"])
        picks = {quiz_bank.pick_key(sent, rng) for _ in range(30)}
        # Only the one unsent quiz question, or (keto/duel used up) any of theirs.
        for key in picks:
            if key.startswith("quiz:"):
                self.assertEqual(key, pools["quiz"][-1])
        self.assertTrue({k.split(":")[0] for k in picks} >= {"quiz", "keto", "duel"})

    def test_option_order_is_stable_and_keeps_yes_no(self):
        item = quiz_bank.build_item("quiz:q05")
        self.assertEqual(quiz_bank.option_order(item, 7), quiz_bank.option_order(item, 7))
        self.assertEqual(sorted(quiz_bank.option_order(item, 7)), [0, 1, 2, 3])
        orders = {tuple(quiz_bank.option_order(item, n)) for n in range(20)}
        self.assertGreater(len(orders), 1)                    # the right one isn't always A
        self.assertEqual(quiz_bank.option_order(quiz_bank.build_item("keto:Asal"), 3), [0, 1])


if __name__ == "__main__":
    unittest.main()
