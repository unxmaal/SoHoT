import unittest

from atlas.shipping import invert
from atlas import shipping


class Shipping(unittest.TestCase):
    def test_invert(self):
        self.assertEqual(invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(invert({}), {})
        self.assertEqual(invert({'x': 'y'}), {'y': ['x']})

    def test_chunk(self):
        self.assertEqual(shipping.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(shipping.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
