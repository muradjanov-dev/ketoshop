"""Chakana va optom narxini 1 kg ga keltirib solishtirish (admin sayti)."""
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import b2b_pricing as bp


class PackSizeTest(unittest.TestCase):
    def test_sizes_from_names(self):
        cases = {
            "Bodom uni 200gr": (0.2, "kg"),
            "Эритритол 1000 гр": (1.0, "kg"),
            "Alluloza 1,5 кг": (1.5, "kg"),
            "Qora Solod 1kg": (1.0, "kg"),
            "Zaytun yog'i, Ispaniya (5 l)": (5.0, "l"),
            "Tabiiy GHEE 1000ml": (1.0, "l"),
            "Set 2×200gr — 1kg": (1.0, "kg"),
        }
        for name, (size, base) in cases.items():
            got = bp.pack_size(name)
            self.assertIsNotNone(got, name)
            self.assertAlmostEqual(got[0], size, msg=name)
            self.assertEqual(got[1], base, name)

    def test_no_size_no_guess(self):
        for name in ("Stevia", "Grechka uni", "Vitamin D3", ""):
            self.assertIsNone(bp.pack_size(name), name)


class CompareTest(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(bp.sale_kind({"b2b_only": True, "b2b_price": 9000}), "b2b_only")
        self.assertEqual(bp.sale_kind({"b2b_price": 9000}), "both")
        self.assertEqual(bp.sale_kind({"b2b_price": 0}), "retail")

    def test_wholesale_cheaper_per_kg(self):
        c = bp.compare({"name": "Bodom uni 200gr", "price": 45000, "b2b_price": 180000})
        self.assertEqual(c["retail_per_base"], 225000)   # 45 000 / 0.2 kg
        self.assertEqual(c["diff_som"], 45000)
        self.assertEqual(c["diff_pct"], 20.0)
        self.assertEqual(c["pack"], "200 gr")

    def test_wholesale_dearer_is_negative(self):
        c = bp.compare({"name": "Un 1kg", "price": 10000, "b2b_price": 12000})
        self.assertEqual(c["diff_som"], -2000)
        self.assertEqual(c["diff_pct"], -20.0)

    def test_unknown_size_and_b2b_only_have_no_retail_comparison(self):
        self.assertIsNone(bp.compare({"name": "Stevia", "price": 15000, "b2b_price": 60000})["diff_som"])
        c = bp.compare({"name": "Un 1kg", "price": 0, "b2b_price": 9000, "b2b_only": True})
        self.assertEqual(c["kind"], "b2b_only")
        self.assertIsNone(c["retail_per_base"])


if __name__ == "__main__":
    unittest.main()
