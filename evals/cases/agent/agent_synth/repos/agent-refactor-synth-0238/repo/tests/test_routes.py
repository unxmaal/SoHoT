import unittest

from orchard import routes


class Routes(unittest.TestCase):
    def test_cargo_view(self):
        self.assertEqual(routes.cargo_view([3, 1, 3, 2, 1]), {'cargo_view': [3, 1, 2]})
        self.assertEqual(routes.cargo_view(['b', 'a', 'b']), {'cargo_view': ['b', 'a']})

    def test_invert(self):
        self.assertEqual(routes.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(routes.invert({}), {})

    def test_weighted_mean(self):
        self.assertEqual(routes.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(routes.weighted_mean([10, 20], [1, 3]), 17.5)
