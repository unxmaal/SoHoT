import unittest

from compass import summary


class Summary(unittest.TestCase):
    def test_deck_entry(self):
        self.assertEqual(summary.deck_entry(2024), {'deck_entry': True})
        self.assertEqual(summary.deck_entry(1900), {'deck_entry': False})

    def test_ferry_check(self):
        self.assertEqual(summary.ferry_check(0), {'ferry_check': '$0.00'})
        self.assertEqual(summary.ferry_check(123456), {'ferry_check': '$1,234.56'})

    def test_buoy_line(self):
        self.assertEqual(summary.buoy_line('1h30m'), {'buoy_line': 5400})
        self.assertEqual(summary.buoy_line('45s'), {'buoy_line': 45})

    def test_buoy_figure(self):
        self.assertEqual(summary.buoy_figure({'tea': 3, 'milk': 3, 'jam': 1}, 2), {'buoy_figure': ['milk', 'tea']})
        self.assertEqual(summary.buoy_figure({'a': 1}, 5), {'buoy_figure': ['a']})

    def test_dock_summary(self):
        self.assertEqual(summary.dock_summary([3, 1, 3, 2, 1]), {'dock_summary': [3, 1, 2]})
        self.assertEqual(summary.dock_summary(['b', 'a', 'b']), {'dock_summary': ['b', 'a']})
