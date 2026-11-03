import unittest

from compass import billing
from compass import kitchen


class Hidden(unittest.TestCase):
    def test_billing_dedupe(self):
        self.assertEqual(billing.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(billing.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(billing.dedupe([]), [])
        self.assertEqual(billing.dedupe([1, 1, 1]), [1])

    def test_billing_running_total(self):
        self.assertEqual(billing.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(billing.running_total([]), [])
        self.assertEqual(billing.running_total([5]), [5])
        self.assertEqual(billing.running_total([2, -2, 2]), [2, 0, 2])

    def test_kitchen_moving_average(self):
        self.assertEqual(kitchen.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(kitchen.moving_average([5], 1), [5.0])
        self.assertEqual(kitchen.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(kitchen.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            kitchen.moving_average([1, 2], 0)

    def test_kitchen_is_leap(self):
        self.assertEqual(kitchen.is_leap(2024), True)
        self.assertEqual(kitchen.is_leap(1900), False)
        self.assertEqual(kitchen.is_leap(2000), True)
        self.assertEqual(kitchen.is_leap(2023), False)
        self.assertEqual(kitchen.is_leap(2400), True)
        self.assertEqual(kitchen.is_leap(2100), False)

    def test_feature(self):
        self.assertEqual(billing.running_total([1, 2], start=10), [11, 13])
        self.assertEqual(billing.running_total([], start=4), [])
        self.assertEqual(billing.running_total([3], start=-3), [0])
