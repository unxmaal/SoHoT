import unittest

from orchard import report


class Report(unittest.TestCase):
    def test_tide_total(self):
        self.assertEqual(report.tide_total('aaab'), {'tide_total': [('a', 3), ('b', 1)]})
        self.assertEqual(report.tide_total(''), {'tide_total': []})

    def test_rope_check(self):
        self.assertEqual(report.rope_check([1, 2, 3, 4, 5], 2), {'rope_check': [[1, 2], [3, 4], [5]]})
        self.assertEqual(report.rope_check([1, 2, 3, 4], 2), {'rope_check': [[1, 2], [3, 4]]})

    def test_anchor_view(self):
        self.assertEqual(report.anchor_view(5, 0, 10), {'anchor_view': 5})
        self.assertEqual(report.anchor_view(-3, 0, 10), {'anchor_view': 0})

    def test_harbor_view(self):
        self.assertEqual(report.harbor_view(0), {'harbor_view': '$0.00'})
        self.assertEqual(report.harbor_view(123456), {'harbor_view': '$1,234.56'})

    def test_deck_row(self):
        self.assertEqual(report.deck_row({'tea': 3, 'milk': 3, 'jam': 1}, 2), {'deck_row': ['milk', 'tea']})
        self.assertEqual(report.deck_row({'a': 1}, 5), {'deck_row': ['a']})
        self.assertEqual(report.deck_row({'x': 2, 'y': 5, 'z': 2}, 2), {'deck_row': ['y', 'x']})
