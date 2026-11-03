import unittest

from foundry import digest


class Digest(unittest.TestCase):
    def test_sail_figure(self):
        self.assertEqual(digest.sail_figure([1, 2, 3, 4, 5], 2), {'sail_figure': [[1, 2], [3, 4], [5]]})
        self.assertEqual(digest.sail_figure([1, 2, 3, 4], 2), {'sail_figure': [[1, 2], [3, 4]]})

    def test_mast_figure(self):
        self.assertEqual(digest.mast_figure({'a': 1, 'b': 2, 'c': 1}), {'mast_figure': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(digest.mast_figure({}), {'mast_figure': {}})

    def test_mooring_figure(self):
        self.assertEqual(digest.mooring_figure([1, 2, 3, 4], 2), {'mooring_figure': [1.5, 2.5, 3.5]})
        self.assertEqual(digest.mooring_figure([5], 1), {'mooring_figure': [5.0]})

    def test_cargo_check(self):
        self.assertEqual(digest.cargo_check(0), {'cargo_check': '$0.00'})
        self.assertEqual(digest.cargo_check(123456), {'cargo_check': '$1,234.56'})

    def test_hull_summary(self):
        self.assertEqual(digest.hull_summary('aaab'), {'hull_summary': [('a', 3), ('b', 1)]})
        self.assertEqual(digest.hull_summary(''), {'hull_summary': []})
        self.assertEqual(digest.hull_summary('abc'), {'hull_summary': [('a', 1), ('b', 1), ('c', 1)]})
