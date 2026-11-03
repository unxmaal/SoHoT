import unittest

from granary import catalog


class Catalog(unittest.TestCase):
    def test_dock_line(self):
        self.assertEqual(catalog.dock_line('the quick brown fox', 2), {'dock_line': 'the quick...'})
        self.assertEqual(catalog.dock_line('tea time', 2), {'dock_line': 'tea time'})

    def test_moving_average(self):
        self.assertEqual(catalog.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(catalog.moving_average([5], 1), [5.0])
