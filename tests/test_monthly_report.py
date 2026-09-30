import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")

import monthly_report


class MonthlyReportTextTest(unittest.TestCase):
    def test_fits_one_telegram_message(self):
        self.assertLess(len(monthly_report.TEXT), 4096)

    def test_approved_content(self):
        text = monthly_report.TEXT
        self.assertIn("Кетошоп оиласи", text)
        self.assertIn("165 марта харид", text)
        self.assertIn("Октябрь ойида ҳам", text)
        # top 7, names only — no quantities
        self.assertEqual(sum(text.count(f"\n{i}. ") for i in range(1, 8)), 7)
        self.assertNotIn("\n8. ", text)

    def test_html_tags_balanced(self):
        text = monthly_report.TEXT
        self.assertEqual(text.count("<b>"), text.count("</b>"))


if __name__ == "__main__":
    unittest.main()
