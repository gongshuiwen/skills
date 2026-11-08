import unittest
from decimal import Decimal
from pricing import quote_total, invoice_total

class PriceRulesTests(unittest.TestCase):
    def test_quote_basic(self):
        self.assertEqual(quote_total([("5.00", 2), ("2.25", 1)]), Decimal("12.25"))

    def test_invoice_member(self):
        self.assertEqual(invoice_total([("10.00", 2)], member=True), Decimal("19.00"))

    def test_invalid_quantity(self):
        with self.assertRaises(ValueError):
            quote_total([("5.00", 0)])

    def test_round_half_up(self):
        self.assertEqual(invoice_total([("1.005", 1)]), Decimal("1.01"))

if __name__ == "__main__":
    unittest.main()
