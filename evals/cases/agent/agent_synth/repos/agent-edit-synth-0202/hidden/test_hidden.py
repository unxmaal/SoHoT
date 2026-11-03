import unittest

from foundry import sensors
from foundry import orders
from foundry import billing
from foundry import metrics


class Hidden(unittest.TestCase):
    def test_sensors_luhn_valid(self):
        self.assertEqual(sensors.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(sensors.luhn_valid('79927398713'), True)
        self.assertEqual(sensors.luhn_valid('79927398710'), False)
        self.assertEqual(sensors.luhn_valid(''), False)
        self.assertEqual(sensors.luhn_valid('059'), True)

    def test_sensors_median(self):
        self.assertEqual(sensors.median([3, 1, 2]), 2)
        self.assertEqual(sensors.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(sensors.median([5]), 5)
        self.assertEqual(sensors.median([1, 2]), 1.5)
        self.assertEqual(sensors.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            sensors.median([])

    def test_orders_word_count(self):
        self.assertEqual(orders.word_count('a b'), 2)
        self.assertEqual(orders.word_count('  tea  and   milk '), 3)
        self.assertEqual(orders.word_count(''), 0)
        self.assertEqual(orders.word_count('one'), 1)

    def test_orders_snake_case(self):
        self.assertEqual(orders.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(orders.snake_case('plain'), 'plain')
        self.assertEqual(orders.snake_case('A'), 'a')
        self.assertEqual(orders.snake_case('ShipToCity'), 'ship_to_city')

    def test_billing_invert(self):
        self.assertEqual(billing.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(billing.invert({}), {})
        self.assertEqual(billing.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(billing.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_billing_rle(self):
        self.assertEqual(billing.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(billing.rle(''), [])
        self.assertEqual(billing.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(billing.rle('zz'), [('z', 2)])

    def test_metrics_weighted_mean(self):
        self.assertEqual(metrics.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(metrics.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(metrics.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            metrics.weighted_mean([5, 5], [0, 0])
        self.assertEqual(metrics.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_metrics_dedupe(self):
        self.assertEqual(metrics.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(metrics.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(metrics.dedupe([]), [])
        self.assertEqual(metrics.dedupe([1, 1, 1]), [1])

    def test_feature(self):
        with self.assertRaises(ValueError):
            metrics.weighted_mean([1, 2, 3], [1, 1])
        with self.assertRaises(ValueError):
            metrics.weighted_mean([4], [1, 2])
