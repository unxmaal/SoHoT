import unittest

from mill import budget


class Budget(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(budget.clamp(5, 0, 10), 5)
        self.assertEqual(budget.clamp(-3, 0, 10), 0)
        self.assertEqual(budget.clamp(15, 0, 10), 10)

    def test_is_leap(self):
        self.assertEqual(budget.is_leap(2024), True)
        self.assertEqual(budget.is_leap(1900), False)
        self.assertEqual(budget.is_leap(2000), True)
