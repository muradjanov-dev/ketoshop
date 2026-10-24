"""Saytda qushlar bilan klassik musiqa (egasi, 2026-10-24). Birdsong moduli
node'da soxta Web Audio bilan ishga tushiriladi (tests/music_check.js) —
hech qanday ovoz chiqmaydi."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class SiteMusicTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = subprocess.run(["node", str(ROOT / "tests" / "music_check.js")],
                             capture_output=True, text=True, check=True, cwd=ROOT).stdout
        cls.r = json.loads(out)

    def test_plays_after_the_first_tap(self):
        self.assertEqual(self.r["firstPiece"], "0")                   # Bach first
        self.assertGreater(self.r["afterTenSeconds"], 30)
        self.assertTrue(self.r["notesInOrder"])
        self.assertGreater(self.r["lowest"], 60)                     # nothing below B1
        self.assertLess(self.r["highest"], 2000)                     # nothing shrill

    def test_rests_on_the_ordering_screens(self):
        self.assertTrue(self.r["silentAtCheckout"])
        self.assertTrue(self.r["backAfterCheckout"])

    def test_off_and_on_again_moves_to_the_next_piece(self):
        self.assertTrue(self.r["silentWhenOff"])
        self.assertEqual(self.r["offToast"], "OFF")
        self.assertEqual(self.r["pieceAfterToggle"], "1")
        self.assertIn("Kanon", self.r["onToast"])

    def test_one_piece_follows_another(self):
        self.assertTrue(self.r["autoAdvanced"])


if __name__ == "__main__":
    unittest.main()
