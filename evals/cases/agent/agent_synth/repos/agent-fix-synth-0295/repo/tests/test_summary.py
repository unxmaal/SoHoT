import unittest

from wharf import summary


class Summary(unittest.TestCase):
    def test_sail_check(self):
        self.assertEqual(summary.sail_check({'a': 1, 'b': 2, 'c': 1}), {'sail_check': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(summary.sail_check({}), {'sail_check': {}})

    def test_anchor_figure(self):
        self.assertEqual(summary.anchor_figure(0), {'anchor_figure': '$0.00'})
        self.assertEqual(summary.anchor_figure(123456), {'anchor_figure': '$1,234.56'})

    def test_buoy_row(self):
        self.assertEqual(summary.buoy_row(95), {'buoy_row': 'A'})
        self.assertEqual(summary.buoy_row(90), {'buoy_row': 'A'})

    def test_crate_view(self):
        self.assertEqual(summary.crate_view(5, 0, 10), {'crate_view': 5})
        self.assertEqual(summary.crate_view(-3, 0, 10), {'crate_view': 0})

    def test_sail_entry(self):
        self.assertEqual(summary.sail_entry([1, 2, 3, 4, 5], 2), {'sail_entry': [[1, 2], [3, 4], [5]]})
        self.assertEqual(summary.sail_entry([1, 2, 3, 4], 2), {'sail_entry': [[1, 2], [3, 4]]})
        self.assertEqual(summary.sail_entry(['a'], 1), {'sail_entry': [['a']]})
