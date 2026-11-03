import unittest

from harbor import budget


class Budget(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(budget.clamp(5, 0, 10), 5)
        self.assertEqual(budget.clamp(-3, 0, 10), 0)
        self.assertEqual(budget.clamp(15, 0, 10), 10)

    def test_bucket(self):
        self.assertEqual(budget.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(budget.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(budget.bucket(12, [0, 5, 10]), 3)
