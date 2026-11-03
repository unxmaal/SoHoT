import unittest

from lantern import overview


class Overview(unittest.TestCase):
    def test_cargo_line(self):
        self.assertEqual(overview.cargo_line('the quick brown fox', 2), {'cargo_line': 'the quick...'})
        self.assertEqual(overview.cargo_line('tea time', 2), {'cargo_line': 'tea time'})

    def test_sail_row(self):
        self.assertEqual(overview.sail_row([1, 2, 3, 4], 2), {'sail_row': [1.5, 2.5, 3.5]})
        self.assertEqual(overview.sail_row([5], 1), {'sail_row': [5.0]})

    def test_harbor_summary(self):
        self.assertEqual(overview.harbor_summary(2024), {'harbor_summary': True})
        self.assertEqual(overview.harbor_summary(1900), {'harbor_summary': False})

    def test_anchor_entry(self):
        self.assertEqual(overview.anchor_entry('aaab'), {'anchor_entry': [('a', 3), ('b', 1)]})
        self.assertEqual(overview.anchor_entry(''), {'anchor_entry': []})

    def test_keel_line(self):
        self.assertEqual(overview.keel_line([1, 2, 3], [1, 1, 1]), {'keel_line': 2.0})
        self.assertEqual(overview.keel_line([10, 20], [1, 3]), {'keel_line': 17.5})
        self.assertEqual(overview.keel_line([4], [2]), {'keel_line': 4.0})
