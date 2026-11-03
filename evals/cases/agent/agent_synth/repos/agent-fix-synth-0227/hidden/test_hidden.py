import unittest

from lantern import stock
from lantern import shipping
from lantern import catalog


class Hidden(unittest.TestCase):
    def test_stock_luhn_valid(self):
        self.assertEqual(stock.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(stock.luhn_valid('79927398713'), True)
        self.assertEqual(stock.luhn_valid('79927398710'), False)
        self.assertEqual(stock.luhn_valid(''), False)
        self.assertEqual(stock.luhn_valid('059'), True)

    def test_stock_running_total(self):
        self.assertEqual(stock.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(stock.running_total([]), [])
        self.assertEqual(stock.running_total([5]), [5])
        self.assertEqual(stock.running_total([2, -2, 2]), [2, 0, 2])

    def test_stock_grade(self):
        self.assertEqual(stock.grade(95), 'A')
        self.assertEqual(stock.grade(90), 'A')
        self.assertEqual(stock.grade(85), 'B')
        self.assertEqual(stock.grade(80), 'B')
        self.assertEqual(stock.grade(61), 'D')
        self.assertEqual(stock.grade(59), 'F')
        self.assertEqual(stock.grade(0), 'F')

    def test_shipping_weighted_mean(self):
        self.assertEqual(shipping.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(shipping.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(shipping.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            shipping.weighted_mean([5, 5], [0, 0])
        self.assertEqual(shipping.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_shipping_invert(self):
        self.assertEqual(shipping.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(shipping.invert({}), {})
        self.assertEqual(shipping.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(shipping.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_catalog_rle(self):
        self.assertEqual(catalog.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(catalog.rle(''), [])
        self.assertEqual(catalog.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(catalog.rle('zz'), [('z', 2)])

    def test_catalog_moving_average(self):
        self.assertEqual(catalog.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(catalog.moving_average([5], 1), [5.0])
        self.assertEqual(catalog.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(catalog.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            catalog.moving_average([1, 2], 0)
