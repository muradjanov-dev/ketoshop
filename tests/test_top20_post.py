import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")

import top20_post


class TopPostTest(unittest.TestCase):
    def test_text(self):
        t = top20_post.TEXT
        self.assertLess(len(t), 4096)                       # one Telegram message
        self.assertEqual(t.count("<b>"), t.count("</b>"))
        self.assertIn("70 та маҳсулоти", t)
        self.assertEqual(sum(f"\n{i}. " in t for i in range(1, 71)), 70)
        self.assertNotIn("\n71. ", t)
        self.assertIn("@ketoshop_uz — Сизнинг кето дўконингиз", t)
        self.assertNotIn("@ketoshopbot", t)                  # owner removed the order line
        self.assertIn("етказишда давом этамиз", t)
        self.assertNotIn("Jo'xori", t)                       # archived product left out


if __name__ == "__main__":
    unittest.main()
