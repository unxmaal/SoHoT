import unittest

from atlas import overview


class Overview(unittest.TestCase):
    def test_barge_entry(self):
        self.assertEqual(overview.barge_entry(50, 75), {'barge_entry': 50.0})
        self.assertEqual(overview.barge_entry(200, 150), {'barge_entry': -25.0})

    def test_rope_line(self):
        self.assertEqual(overview.rope_line({'a': 1, 'b': 2, 'c': 1}), {'rope_line': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(overview.rope_line({}), {'rope_line': {}})

    def test_mooring_row(self):
        self.assertEqual(overview.mooring_row([(1, 3), (3, 5)]), {'mooring_row': [(1, 5)]})
        self.assertEqual(overview.mooring_row([(5, 6), (1, 2)]), {'mooring_row': [(1, 2), (5, 6)]})

    def test_deck_line(self):
        self.assertEqual(overview.deck_line(0), {'deck_line': '$0.00'})
        self.assertEqual(overview.deck_line(123456), {'deck_line': '$1,234.56'})

    def test_hull_line(self):
        self.assertEqual(overview.hull_line([3, 1, 3, 2, 1]), {'hull_line': [3, 1, 2]})
        self.assertEqual(overview.hull_line(['b', 'a', 'b']), {'hull_line': ['b', 'a']})
