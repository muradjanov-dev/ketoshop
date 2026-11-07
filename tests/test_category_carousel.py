"""Katalogdagi kategoriyalar karuseli (egasi, 2026-11-07: "kategoriyalar ham
karusel bo'lib sekin aylanib turadigan bo'lsin").

The row drifts left on its own and loops over a second, hidden copy of the
tiles. Measured in a real browser while writing this (Edge, 412 px): ~20 px a
second, stops under a finger, goes on 4 s after release, wraps without a jump.
These tests pin the loop arithmetic and the wiring."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "webapp" / "index.html").read_text(encoding="utf-8").replace("\r\n", "\n")


def css_block(selector: str) -> str:
    m = re.search(re.escape(selector) + r" \{(.*?)\n  \}", HTML, re.S)
    assert m, selector
    return m.group(1)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class DriftStepTest(unittest.TestCase):
    def step(self, *calls):
        block = HTML[HTML.index("function tileDriftStep("):HTML.index("const TileDrift = (")]
        code = block + "\nprocess.stdout.write(JSON.stringify([" + ",".join(
            f"tileDriftStep({a}, {b}, {c}, {d})" for a, b, c, d in calls) + "]));"
        out = subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    def test_slow_and_steady(self):
        # 20 px a second: one 16.7 ms frame is a third of a pixel, a second is 20 px.
        a, b = self.step((0, 1000 / 60, 750, 20), (100, 1000, 750, 20))
        self.assertAlmostEqual(a, 20 / 60, places=6)
        self.assertEqual(b, 102)          # a long gap counts as 100 ms at most — no leap after a pause

    def test_loops_back_by_one_set(self):
        (x,) = self.step((749, 100, 750, 20))
        self.assertAlmostEqual(x, 1.0)    # 751 → the same picture one set earlier

    def test_odd_input_stays_put(self):
        self.assertEqual(self.step((10, -50, 750, 20)), [10])
        self.assertEqual(self.step((800, 0, 0, 20)), [800])   # no loop measured — never wraps


class WiringTest(unittest.TestCase):
    def test_no_snapping_fights_the_drift(self):
        self.assertNotIn("scroll-snap", css_block("  .cat-tiles"))
        self.assertNotIn("scroll-snap", css_block("  .cat-tile"))

    def test_two_tile_rows_kept(self):
        s = css_block("  .cat-tiles .ct-set")
        self.assertIn("grid-template-rows: repeat(2, auto)", s)
        self.assertIn("grid-auto-columns: var(--ct-col", s)

    def test_copy_is_hidden_from_screen_readers_and_tab(self):
        drift = HTML[HTML.index("const TileDrift = ("):]
        self.assertIn("copy.setAttribute('aria-hidden', 'true')", drift)
        self.assertIn("b.tabIndex = -1", drift)

    def test_taps_work_on_both_copies(self):
        render = HTML[HTML.index("function renderCatalogTiles("):HTML.index("function tileDriftStep(")]
        self.assertIn("box.onclick = e =>", render)
        self.assertIn("e.target.closest('.cat-tile')", render)
        self.assertNotIn("b.onclick", render)             # a clone would lose a per-tile handler
        self.assertIn("TileDrift.attach(box, set)", render)
        self.assertIn("TileDrift.visible(e.isIntersecting)", render)

    def test_pauses(self):
        drift = HTML[HTML.index("const TileDrift = ("):]
        for hook in ("'touchstart', grab", "'touchend', free", "'wheel', hold", "'scroll'",
                     "'visibilitychange', run", "document.hidden"):
            self.assertIn(hook, drift)
        self.assertIn("const RESUME_MS = 4000", drift)
        self.assertIn("const SPEED = 20", drift)


if __name__ == "__main__":
    unittest.main()
