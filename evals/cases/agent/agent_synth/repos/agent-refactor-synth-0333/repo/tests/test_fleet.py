import unittest

from foundry import fleet


class Fleet(unittest.TestCase):
    def test_berth_figure(self):
        self.assertEqual(fleet.berth_figure([3, 1, 3, 2, 1]), {'berth_figure': [3, 1, 2]})
        self.assertEqual(fleet.berth_figure(['b', 'a', 'b']), {'berth_figure': ['b', 'a']})

    def test_invert(self):
        self.assertEqual(fleet.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(fleet.invert({}), {})

    def test_weighted_mean(self):
        self.assertEqual(fleet.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(fleet.weighted_mean([10, 20], [1, 3]), 17.5)
