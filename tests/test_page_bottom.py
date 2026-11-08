"""Sahifa oxiri menyu ostida qolmaydi (egasi, 2026-11-08: mijozning «Tuz»
skrinshoti — Bosh sahifaning oxirgi qatori, nomi va narxi pastki menyu
ostida).

Measured in Edge (390×760) while writing this: the last price now ends
125 px above the dock (was 73, with the section's last line 18 px above the
dock and under the floating 🔇 button), and when Telegram reports a 48 px
bottom inset the dock and the page end both rise by it."""
import os
import re
import unittest

PAGE = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webapp", "index.html"),
            encoding="utf-8").read()


class BottomTest(unittest.TestCase):
    def test_telegram_bottom_inset_counts(self):
        m = re.search(r"--safe-b:(.*?);", PAGE, re.S)
        self.assertIn("env(safe-area-inset-bottom", m.group(1))
        self.assertIn("--tg-safe-area-inset-bottom", m.group(1))
        self.assertIn("--tg-content-safe-area-inset-bottom", m.group(1))

    def test_page_ends_above_the_floating_buttons(self):
        self.assertIn("--float-h:", PAGE)
        self.assertIn("padding-bottom: calc(var(--dock-h) + var(--dock-gap) * 2 + var(--safe-b) + var(--float-h) + 8px);",
                      PAGE)


if __name__ == "__main__":
    unittest.main()
