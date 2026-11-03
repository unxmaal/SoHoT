import unittest

from granary import routes


class Routes(unittest.TestCase):
    def test_weighted_mean(self):
        self.assertEqual(routes.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(routes.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(routes.weighted_mean([4], [2]), 4.0)

    def test_invert(self):
        self.assertEqual(routes.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(routes.invert({}), {})
        self.assertEqual(routes.invert({'x': 'y'}), {'y': ['x']})
