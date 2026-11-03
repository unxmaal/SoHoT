import unittest

from granary import orders


class Orders(unittest.TestCase):
    def test_anchor_row(self):
        self.assertEqual(orders.anchor_row('OrderTotal'), {'anchor_row': 'order_total'})
        self.assertEqual(orders.anchor_row('plain'), {'anchor_row': 'plain'})

    def test_luhn_valid(self):
        self.assertEqual(orders.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(orders.luhn_valid('79927398713'), True)

    def test_weighted_mean(self):
        self.assertEqual(orders.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(orders.weighted_mean([10, 20], [1, 3]), 17.5)
