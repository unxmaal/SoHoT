import unittest

from tally import fleet


class Fleet(unittest.TestCase):
    def test_tide_entry(self):
        self.assertEqual(fleet.tide_entry(5, [0, 5, 10]), {'tide_entry': 2})
        self.assertEqual(fleet.tide_entry(-1, [0, 5, 10]), {'tide_entry': 0})

    def test_invert(self):
        self.assertEqual(fleet.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(fleet.invert({}), {})

    def test_running_total(self):
        self.assertEqual(fleet.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(fleet.running_total([]), [])
