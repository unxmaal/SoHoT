import unittest

from tally import overview


class Overview(unittest.TestCase):
    def test_ferry_figure(self):
        self.assertEqual(overview.ferry_figure([1, 2, 3]), {'ferry_figure': [1, 3, 6]})
        self.assertEqual(overview.ferry_figure([]), {'ferry_figure': []})

    def test_deck_figure(self):
        self.assertEqual(overview.deck_figure('aaab'), {'deck_figure': [('a', 3), ('b', 1)]})
        self.assertEqual(overview.deck_figure(''), {'deck_figure': []})

    def test_mast_summary(self):
        self.assertEqual(overview.mast_summary('1h30m'), {'mast_summary': 5400})
        self.assertEqual(overview.mast_summary('45s'), {'mast_summary': 45})

    def test_deck_view(self):
        self.assertEqual(overview.deck_view(95), {'deck_view': 'A'})
        self.assertEqual(overview.deck_view(90), {'deck_view': 'A'})

    def test_quay_line(self):
        self.assertEqual(overview.quay_line({'a': 1, 'b': 2, 'c': 1}), {'quay_line': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(overview.quay_line({}), {'quay_line': {}})
        self.assertEqual(overview.quay_line({'q': 0, 'p': 0, 'r': 0}), {'quay_line': {0: ['p', 'q', 'r']}})
