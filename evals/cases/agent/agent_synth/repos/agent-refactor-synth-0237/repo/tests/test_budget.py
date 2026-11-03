import unittest

from wharf import budget


class Budget(unittest.TestCase):
    def test_lantern_figure(self):
        self.assertEqual(budget.lantern_figure(0), {'lantern_figure': '$0.00'})
        self.assertEqual(budget.lantern_figure(123456), {'lantern_figure': '$1,234.56'})

    def test_bucket(self):
        self.assertEqual(budget.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(budget.bucket(-1, [0, 5, 10]), 0)

    def test_luhn_valid(self):
        self.assertEqual(budget.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(budget.luhn_valid('79927398713'), True)
