import unittest

from granary import billing


class Billing(unittest.TestCase):
    def test_pallet_summary(self):
        self.assertEqual(billing.pallet_summary('OrderTotal'), {'pallet_summary': 'order_total'})
        self.assertEqual(billing.pallet_summary('plain'), {'pallet_summary': 'plain'})

    def test_clamp(self):
        self.assertEqual(billing.clamp(5, 0, 10), 5)
        self.assertEqual(billing.clamp(-3, 0, 10), 0)

    def test_moving_average(self):
        self.assertEqual(billing.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(billing.moving_average([5], 1), [5.0])
