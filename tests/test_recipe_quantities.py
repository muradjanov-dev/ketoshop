"""Retseptlarda har bir masalliqning miqdori va qadamma-qadam tayyorlash
bo'lsin (egasi, 2026-10-16: "retseptlarda masalliqlarning miqdorini ham
ko'rsating ... savol tug'dirmaydigan darajada batafsil va tushunarli qilib
yoz"). Bazaga ulanmasdan."""
import os
import re
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import broadcast_tips
import reco_content
from translit import lat_to_cyr

QTY = re.compile(
    r"\d|½|¼|\b(bir|yarim|chimdim|hovuch|stakan|qoshiq|dona|ta\b|bo'lak|bog'|tishcha|chashka|banka|"
    r"щепот|ложк|стакан|горст|шт|ломтик|пучок|зубчик|половин|банк)", re.I)


def reco_recipes():
    out = []
    for p in reco_content.PROFILES + list(reco_content.CATEGORY_GENERIC_PROFILES.values()) + [reco_content.DEFAULT_PROFILE]:
        out += p["recipes"]
    return out + [c["recipe"] for c in reco_content.COMBOS]


class RecoRecipesTest(unittest.TestCase):
    HEADS = {"uz": ("🧾 <b>Masalliqlar:</b>", "👩‍🍳 <b>Tayyorlash:</b>"),
             "ru": ("🧾 <b>Ингредиенты:</b>", "👩‍🍳 <b>Приготовление:</b>")}

    def test_every_ingredient_has_an_amount_and_steps_are_numbered(self):
        for r in reco_recipes():
            for lang, (ing_head, step_head) in self.HEADS.items():
                text = r[lang]
                title = re.match(r"<b>(.*?)</b>", text).group(1)
                self.assertIn(ing_head, text, title)
                self.assertIn(step_head, text, title)
                ings = [l[2:] for l in text.split(ing_head)[1].split(step_head)[0].split("\n") if l.startswith("• ")]
                self.assertTrue(ings, title)
                for ing in ings:
                    self.assertRegex(ing, QTY, f"{title}: «{ing}» has no amount")
                self.assertGreaterEqual(len(re.findall(r"^\d+\. ", text, re.M)), 2, title)
                self.assertEqual(text.count("<b>"), text.count("</b>"), title)

    def test_cyrillic_uzbek_reads_cleanly(self):
        for r in reco_recipes():
            cyr = re.sub(r"<[^>]+>", "", lat_to_cyr(r["uz"]))
            left = [w for w in re.findall(r"[A-Za-z]{2,}", cyr) if w not in ("MCT", "PP")]
            self.assertEqual(left, [], r["uz"][:60])


class TipsRecipesTest(unittest.TestCase):
    def test_tips_recipes_have_amounts_and_steps(self):
        posts = broadcast_tips._RAW.split("@@@")
        self.assertEqual(len(posts), len(broadcast_tips.TIPS))      # order is tracked by index
        for n, post in enumerate(posts, 1):
            if "Masalliqlar:" not in post:
                continue
            ings_part, _, steps_part = post.split("Masalliqlar:", 1)[1].partition("Tayyorlanishi:")
            self.assertTrue(steps_part, f"post #{n} has no Tayyorlanishi")
            for ing in [l[2:] for l in ings_part.split("\n") if l.startswith("• ")]:
                self.assertRegex(ing, QTY, f"post #{n}: «{ing}» has no amount")
            self.assertGreaterEqual(len(re.findall(r"^\d+\. ", steps_part, re.M)), 2, f"post #{n}")


if __name__ == "__main__":
    unittest.main()
