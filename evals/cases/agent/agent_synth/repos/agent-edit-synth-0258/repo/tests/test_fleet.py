import unittest

from quarry import fleet


class Fleet(unittest.TestCase):
    def test_format_cents(self):
        self.assertEqual(fleet.format_cents(0), '$0.00')
        self.assertEqual(fleet.format_cents(123456), '$1,234.56')
        self.assertEqual(fleet.format_cents(-105), '-$1.05')

    def test_weighted_mean(self):
        self.assertEqual(fleet.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(fleet.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(fleet.weighted_mean([4], [2]), 4.0)
