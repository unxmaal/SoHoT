import unittest

from kiln import pricing


class Pricing(unittest.TestCase):
    def test_weighted_mean(self):
        self.assertEqual(pricing.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(pricing.weighted_mean([10, 20], [1, 3]), 17.5)

    def test_grade(self):
        self.assertEqual(pricing.grade(95), 'A')
        self.assertEqual(pricing.grade(90), 'A')

    def test_luhn_valid(self):
        self.assertEqual(pricing.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(pricing.luhn_valid('79927398713'), True)
