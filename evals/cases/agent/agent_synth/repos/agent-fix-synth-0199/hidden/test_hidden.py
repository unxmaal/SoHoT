import unittest

from depot import tickets
from depot import timesheet
from depot import rosters
from depot import overview


class Hidden(unittest.TestCase):
    def test_tickets_dedupe(self):
        self.assertEqual(tickets.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(tickets.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(tickets.dedupe([]), [])
        self.assertEqual(tickets.dedupe([1, 1, 1]), [1])

    def test_tickets_truncate_words(self):
        self.assertEqual(tickets.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(tickets.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(tickets.truncate_words('', 3), '')
        self.assertEqual(tickets.truncate_words('one two three', 1), 'one...')

    def test_timesheet_top_n(self):
        self.assertEqual(timesheet.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(timesheet.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(timesheet.top_n({}, 2), [])
        self.assertEqual(timesheet.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_timesheet_bucket(self):
        self.assertEqual(timesheet.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(timesheet.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(timesheet.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(timesheet.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(timesheet.bucket(7, []), 0)

    def test_rosters_median(self):
        self.assertEqual(rosters.median([3, 1, 2]), 2)
        self.assertEqual(rosters.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(rosters.median([5]), 5)
        self.assertEqual(rosters.median([1, 2]), 1.5)
        self.assertEqual(rosters.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            rosters.median([])

    def test_rosters_snake_case(self):
        self.assertEqual(rosters.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(rosters.snake_case('plain'), 'plain')
        self.assertEqual(rosters.snake_case('A'), 'a')
        self.assertEqual(rosters.snake_case('ShipToCity'), 'ship_to_city')

    def test_rosters_invert(self):
        self.assertEqual(rosters.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(rosters.invert({}), {})
        self.assertEqual(rosters.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(rosters.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_overview_berth_figure(self):
        self.assertEqual(overview.berth_figure([3, 1, 3, 2, 1]), {'berth_figure': [3, 1, 2]})
        self.assertEqual(overview.berth_figure(['b', 'a', 'b']), {'berth_figure': ['b', 'a']})
        self.assertEqual(overview.berth_figure([]), {'berth_figure': []})
        self.assertEqual(overview.berth_figure([1, 1, 1]), {'berth_figure': [1]})

    def test_overview_deck_entry(self):
        self.assertEqual(overview.deck_entry('the quick brown fox', 2), {'deck_entry': 'the quick...'})
        self.assertEqual(overview.deck_entry('tea time', 2), {'deck_entry': 'tea time'})
        self.assertEqual(overview.deck_entry('', 3), {'deck_entry': ''})
        self.assertEqual(overview.deck_entry('one two three', 1), {'deck_entry': 'one...'})

    def test_overview_deck_summary(self):
        self.assertEqual(overview.deck_summary({'tea': 3, 'milk': 3, 'jam': 1}, 2), {'deck_summary': ['milk', 'tea']})
        self.assertEqual(overview.deck_summary({'a': 1}, 5), {'deck_summary': ['a']})
        self.assertEqual(overview.deck_summary({}, 2), {'deck_summary': []})
        self.assertEqual(overview.deck_summary({'x': 2, 'y': 5, 'z': 2}, 2), {'deck_summary': ['y', 'x']})

    def test_overview_rope_entry(self):
        self.assertEqual(overview.rope_entry(5, [0, 5, 10]), {'rope_entry': 2})
        self.assertEqual(overview.rope_entry(-1, [0, 5, 10]), {'rope_entry': 0})
        self.assertEqual(overview.rope_entry(12, [0, 5, 10]), {'rope_entry': 3})
        self.assertEqual(overview.rope_entry(0, [0, 5, 10]), {'rope_entry': 1})
        self.assertEqual(overview.rope_entry(7, []), {'rope_entry': 0})

    def test_overview_mooring_figure(self):
        self.assertEqual(overview.mooring_figure([3, 1, 2]), {'mooring_figure': 2})
        self.assertEqual(overview.mooring_figure([4, 1, 3, 2]), {'mooring_figure': 2.5})
        self.assertEqual(overview.mooring_figure([5]), {'mooring_figure': 5})
        self.assertEqual(overview.mooring_figure([1, 2]), {'mooring_figure': 1.5})
        self.assertEqual(overview.mooring_figure([10, 2, 38, 23, 38, 23]), {'mooring_figure': 23.0})
        with self.assertRaises(ValueError):
            overview.mooring_figure([])
