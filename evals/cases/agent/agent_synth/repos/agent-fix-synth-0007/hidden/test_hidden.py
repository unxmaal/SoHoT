import unittest

from atlas import ledger
from atlas import rosters
from atlas import kitchen
from atlas import overview


class Hidden(unittest.TestCase):
    def test_ledger_percent_change(self):
        self.assertEqual(ledger.percent_change(50, 75), 50.0)
        self.assertEqual(ledger.percent_change(200, 150), -25.0)
        self.assertEqual(ledger.percent_change(80, 80), 0.0)
        self.assertEqual(ledger.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            ledger.percent_change(0, 5)
        self.assertEqual(ledger.percent_change(-10, -5), -50.0)

    def test_ledger_invert(self):
        self.assertEqual(ledger.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(ledger.invert({}), {})
        self.assertEqual(ledger.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(ledger.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_ledger_merge_ranges(self):
        self.assertEqual(ledger.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(ledger.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(ledger.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(ledger.merge_ranges([]), [])
        self.assertEqual(ledger.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_rosters_format_cents(self):
        self.assertEqual(rosters.format_cents(0), '$0.00')
        self.assertEqual(rosters.format_cents(123456), '$1,234.56')
        self.assertEqual(rosters.format_cents(-105), '-$1.05')
        self.assertEqual(rosters.format_cents(5), '$0.05')
        self.assertEqual(rosters.format_cents(100000000), '$1,000,000.00')

    def test_rosters_is_leap(self):
        self.assertEqual(rosters.is_leap(2024), True)
        self.assertEqual(rosters.is_leap(1900), False)
        self.assertEqual(rosters.is_leap(2000), True)
        self.assertEqual(rosters.is_leap(2023), False)
        self.assertEqual(rosters.is_leap(2400), True)
        self.assertEqual(rosters.is_leap(2100), False)

    def test_rosters_dedupe(self):
        self.assertEqual(rosters.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(rosters.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(rosters.dedupe([]), [])
        self.assertEqual(rosters.dedupe([1, 1, 1]), [1])

    def test_kitchen_chunk(self):
        self.assertEqual(kitchen.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(kitchen.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(kitchen.chunk([], 3), [])
        self.assertEqual(kitchen.chunk(['a'], 1), [['a']])
        self.assertEqual(kitchen.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            kitchen.chunk([1, 2], 0)

    def test_kitchen_median(self):
        self.assertEqual(kitchen.median([3, 1, 2]), 2)
        self.assertEqual(kitchen.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(kitchen.median([5]), 5)
        self.assertEqual(kitchen.median([1, 2]), 1.5)
        self.assertEqual(kitchen.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            kitchen.median([])

    def test_kitchen_luhn_valid(self):
        self.assertEqual(kitchen.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(kitchen.luhn_valid('79927398713'), True)
        self.assertEqual(kitchen.luhn_valid('79927398710'), False)
        self.assertEqual(kitchen.luhn_valid(''), False)
        self.assertEqual(kitchen.luhn_valid('059'), True)

    def test_overview_barge_entry(self):
        self.assertEqual(overview.barge_entry(50, 75), {'barge_entry': 50.0})
        self.assertEqual(overview.barge_entry(200, 150), {'barge_entry': -25.0})
        self.assertEqual(overview.barge_entry(80, 80), {'barge_entry': 0.0})
        self.assertEqual(overview.barge_entry(3, 4), {'barge_entry': 33.33})
        with self.assertRaises(ValueError):
            overview.barge_entry(0, 5)
        self.assertEqual(overview.barge_entry(-10, -5), {'barge_entry': -50.0})

    def test_overview_rope_line(self):
        self.assertEqual(overview.rope_line({'a': 1, 'b': 2, 'c': 1}), {'rope_line': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(overview.rope_line({}), {'rope_line': {}})
        self.assertEqual(overview.rope_line({'x': 'y'}), {'rope_line': {'y': ['x']}})
        self.assertEqual(overview.rope_line({'q': 0, 'p': 0, 'r': 0}), {'rope_line': {0: ['p', 'q', 'r']}})

    def test_overview_mooring_row(self):
        self.assertEqual(overview.mooring_row([(1, 3), (3, 5)]), {'mooring_row': [(1, 5)]})
        self.assertEqual(overview.mooring_row([(5, 6), (1, 2)]), {'mooring_row': [(1, 2), (5, 6)]})
        self.assertEqual(overview.mooring_row([(1, 10), (2, 3)]), {'mooring_row': [(1, 10)]})
        self.assertEqual(overview.mooring_row([]), {'mooring_row': []})
        self.assertEqual(overview.mooring_row([(4, 8), (1, 5)]), {'mooring_row': [(1, 8)]})

    def test_overview_deck_line(self):
        self.assertEqual(overview.deck_line(0), {'deck_line': '$0.00'})
        self.assertEqual(overview.deck_line(123456), {'deck_line': '$1,234.56'})
        self.assertEqual(overview.deck_line(-105), {'deck_line': '-$1.05'})
        self.assertEqual(overview.deck_line(5), {'deck_line': '$0.05'})
        self.assertEqual(overview.deck_line(100000000), {'deck_line': '$1,000,000.00'})

    def test_overview_hull_line(self):
        self.assertEqual(overview.hull_line([3, 1, 3, 2, 1]), {'hull_line': [3, 1, 2]})
        self.assertEqual(overview.hull_line(['b', 'a', 'b']), {'hull_line': ['b', 'a']})
        self.assertEqual(overview.hull_line([]), {'hull_line': []})
        self.assertEqual(overview.hull_line([1, 1, 1]), {'hull_line': [1]})
