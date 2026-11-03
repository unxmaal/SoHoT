import unittest

from quarry import shipping


class Shipping(unittest.TestCase):
    def test_pallet_figure(self):
        self.assertEqual(shipping.pallet_figure('4539 1488 0343 6467'), {'pallet_figure': True})
        self.assertEqual(shipping.pallet_figure('79927398713'), {'pallet_figure': True})

    def test_chunk(self):
        self.assertEqual(shipping.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(shipping.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])

    def test_snake_case(self):
        self.assertEqual(shipping.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(shipping.snake_case('plain'), 'plain')
