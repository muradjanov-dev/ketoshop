"""Lotin ↔ kirill o'girish: so'z boshidagi e, digraflar, tegilmaydigan qismlar."""
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

from translit import lat_to_cyr, cyr_to_lat


class WordInitialETest(unittest.TestCase):
    """Word-initial e is э, mid-word e is е — and "mid-word" has to mean
    after ANY letter. The rule runs after the digraph pass, so by then "ch"
    is already "ч"; a Latin-only test read the e of "pechene" as a fresh word
    and produced "печэне" (and "чэк" for chek, "Чэхия" for Chexiya)."""

    def test_word_initial(self):
        for src, want in (("emas", "эмас"), ("eng", "энг"),
                          ("eritritol", "эритритол"), ("echki", "эчки")):
            self.assertEqual(lat_to_cyr(src), want, src)

    def test_capital_word_initial(self):
        self.assertEqual(lat_to_cyr("Eritritol"), "Эритритол")

    def test_mid_word_after_latin(self):
        for src, want in (("keksa", "кекса"), ("energiya", "энергия"),
                          ("kecha", "кеча")):
            self.assertEqual(lat_to_cyr(src), want, src)

    def test_mid_word_after_a_digraph(self):
        # The regression this test exists for.
        for src, want in (("pechene", "печене"), ("chek", "чек"),
                          ("chempion", "чемпион"), ("Chexiya", "Чехия"),
                          ("sher", "шер")):
            self.assertEqual(lat_to_cyr(src), want, src)

    def test_ye_stays_plain_e(self):
        self.assertEqual(lat_to_cyr("yetarli"), "етарли")


class UntouchedPartsTest(unittest.TestCase):
    def test_html_tags_survive_and_e_after_them_is_word_initial(self):
        self.assertEqual(lat_to_cyr("<b>Eng</b>"), "<b>Энг</b>")

    def test_apostrophe_digraphs(self):
        self.assertEqual(lat_to_cyr("o'zbek"), "ўзбек")
        self.assertEqual(lat_to_cyr("g'alaba"), "ғалаба")


class IdempotenceTest(unittest.TestCase):
    def test_running_twice_changes_nothing(self):
        for src in ("pechene va chek", "Eritritol 500gr", "<b>Eng</b> yaxshi"):
            once = lat_to_cyr(src)
            self.assertEqual(lat_to_cyr(once), once, src)

    def test_round_trip_keeps_meaning(self):
        # Not character-exact (ў/ǒ spellings differ), but a Latin source that
        # went to Cyrillic and back must stay Latin, not turn to mush.
        back = cyr_to_lat(lat_to_cyr("pechene va chek"))
        self.assertIn("chek", back)


if __name__ == "__main__":
    unittest.main(verbosity=1)
