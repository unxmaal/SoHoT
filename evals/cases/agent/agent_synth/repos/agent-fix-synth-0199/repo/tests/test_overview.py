import unittest

from depot import overview


class Overview(unittest.TestCase):
    def test_berth_figure(self):
        self.assertEqual(overview.berth_figure([3, 1, 3, 2, 1]), {'berth_figure': [3, 1, 2]})
        self.assertEqual(overview.berth_figure(['b', 'a', 'b']), {'berth_figure': ['b', 'a']})

    def test_deck_entry(self):
        self.assertEqual(overview.deck_entry('the quick brown fox', 2), {'deck_entry': 'the quick...'})
        self.assertEqual(overview.deck_entry('tea time', 2), {'deck_entry': 'tea time'})

    def test_deck_summary(self):
        self.assertEqual(overview.deck_summary({'tea': 3, 'milk': 3, 'jam': 1}, 2), {'deck_summary': ['milk', 'tea']})
        self.assertEqual(overview.deck_summary({'a': 1}, 5), {'deck_summary': ['a']})

    def test_rope_entry(self):
        self.assertEqual(overview.rope_entry(5, [0, 5, 10]), {'rope_entry': 2})
        self.assertEqual(overview.rope_entry(-1, [0, 5, 10]), {'rope_entry': 0})

    def test_mooring_figure(self):
        self.assertEqual(overview.mooring_figure([3, 1, 2]), {'mooring_figure': 2})
        self.assertEqual(overview.mooring_figure([4, 1, 3, 2]), {'mooring_figure': 2.5})
        self.assertEqual(overview.mooring_figure([1, 2]), {'mooring_figure': 1.5})
