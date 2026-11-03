import unittest

from atlas import shipping


class Shipping(unittest.TestCase):
    def test_berth_check(self):
        self.assertEqual(shipping.berth_check(2024), {'berth_check': True})
        self.assertEqual(shipping.berth_check(1900), {'berth_check': False})

    def test_median(self):
        self.assertEqual(shipping.median([3, 1, 2]), 2)
        self.assertEqual(shipping.median([4, 1, 3, 2]), 2.5)

    def test_running_total(self):
        self.assertEqual(shipping.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(shipping.running_total([]), [])
