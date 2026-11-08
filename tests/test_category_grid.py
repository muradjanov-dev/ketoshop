"""Katalog kategoriyalari pastga qarab (egasi, 2026-11-08: "kategoriyalarni
karuselini o'chir va ularni yonga emas pastga qarab tahla") — PR #167 dagi
o'zi aylanadigan karusel o'rniga oddiy to'r.

Checked in Edge while writing this: 3 tiles a row at 390 and 360 px,
nothing scrolls sideways and nothing moves on its own."""
import os
import re
import unittest

PAGE = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webapp", "index.html"),
            encoding="utf-8").read().replace("\r\n", "\n")


def css_block(selector: str) -> str:
    m = re.search(re.escape(selector) + r" \{(.*?)\n  \}", PAGE, re.S)
    assert m, selector
    return m.group(1)


class GridTest(unittest.TestCase):
    def test_tiles_run_downward(self):
        css = css_block("  .cat-tiles")
        self.assertIn("display: grid", css)
        self.assertIn("grid-template-columns: repeat(auto-fill, minmax(100px, 1fr))", css)
        self.assertNotIn("overflow-x", css)
        self.assertNotIn("grid-auto-flow: column", css)

    def test_carousel_is_gone(self):
        for gone in ("TileDrift", "tileDriftStep", "ct-set", "--ct-col"):
            self.assertNotIn(gone, PAGE, gone)

    def test_taps_and_the_floating_chips_still_work(self):
        render = PAGE[PAGE.index("function renderCatalogTiles("):PAGE.index("function scrollToCatalogList(")]
        self.assertIn("box.appendChild(b)", render)
        self.assertIn("e.target.closest('.cat-tile')", render)
        self.assertIn("chips.classList.toggle('show', !e.isIntersecting)", render)


if __name__ == "__main__":
    unittest.main()
