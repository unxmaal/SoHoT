import unittest

from mill import digest


class Digest(unittest.TestCase):
    def test_anchor_entry(self):
        self.assertEqual(digest.anchor_entry(0), {'anchor_entry': '$0.00'})
        self.assertEqual(digest.anchor_entry(123456), {'anchor_entry': '$1,234.56'})

    def test_hull_line(self):
        self.assertEqual(digest.hull_line({'tea': 3, 'milk': 3, 'jam': 1}, 2), {'hull_line': ['milk', 'tea']})
        self.assertEqual(digest.hull_line({'a': 1}, 5), {'hull_line': ['a']})

    def test_cargo_summary(self):
        self.assertEqual(digest.cargo_summary([1, 2, 3, 4], 2), {'cargo_summary': [1.5, 2.5, 3.5]})
        self.assertEqual(digest.cargo_summary([5], 1), {'cargo_summary': [5.0]})

    def test_lantern_figure(self):
        self.assertEqual(digest.lantern_figure(2024), {'lantern_figure': True})
        self.assertEqual(digest.lantern_figure(1900), {'lantern_figure': False})

    def test_ferry_view(self):
        self.assertEqual(digest.ferry_view([1, 2, 3], [1, 1, 1]), {'ferry_view': 2.0})
        self.assertEqual(digest.ferry_view([10, 20], [1, 3]), {'ferry_view': 17.5})
        self.assertEqual(digest.ferry_view([4], [2]), {'ferry_view': 4.0})
