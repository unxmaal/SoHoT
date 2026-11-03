import unittest

from foundry import billing


class Billing(unittest.TestCase):
    def test_bucket(self):
        self.assertEqual(billing.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(billing.bucket(-1, [0, 5, 10]), 0)

    def test_moving_average(self):
        self.assertEqual(billing.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(billing.moving_average([5], 1), [5.0])
