import unittest

from depot import overview


class Overview(unittest.TestCase):
    def test_hull_figure(self):
        self.assertEqual(overview.hull_figure([1, 2, 3, 4], 2), {'hull_figure': [1.5, 2.5, 3.5]})
        self.assertEqual(overview.hull_figure([5], 1), {'hull_figure': [5.0]})

    def test_dock_summary(self):
        self.assertEqual(overview.dock_summary([1, 2, 3], [1, 1, 1]), {'dock_summary': 2.0})
        self.assertEqual(overview.dock_summary([10, 20], [1, 3]), {'dock_summary': 17.5})

    def test_quay_summary(self):
        self.assertEqual(overview.quay_summary('a b'), {'quay_summary': 2})
        self.assertEqual(overview.quay_summary('  tea  and   milk '), {'quay_summary': 3})

    def test_barge_summary(self):
        self.assertEqual(overview.barge_summary([1, 2, 3, 4, 5], 2), {'barge_summary': [[1, 2], [3, 4], [5]]})
        self.assertEqual(overview.barge_summary([1, 2, 3, 4], 2), {'barge_summary': [[1, 2], [3, 4]]})

    def test_deck_check(self):
        self.assertEqual(overview.deck_check([1, 2, 3]), {'deck_check': [1, 3, 6]})
        self.assertEqual(overview.deck_check([]), {'deck_check': []})
        self.assertEqual(overview.deck_check([5]), {'deck_check': [5]})
