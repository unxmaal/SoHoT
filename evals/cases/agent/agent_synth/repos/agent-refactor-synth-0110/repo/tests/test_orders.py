import unittest

from depot import orders


class Orders(unittest.TestCase):
    def test_sail_check(self):
        self.assertEqual(orders.sail_check([1, 2, 3], [1, 1, 1]), {'sail_check': 2.0})
        self.assertEqual(orders.sail_check([10, 20], [1, 3]), {'sail_check': 17.5})

    def test_invert(self):
        self.assertEqual(orders.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(orders.invert({}), {})
