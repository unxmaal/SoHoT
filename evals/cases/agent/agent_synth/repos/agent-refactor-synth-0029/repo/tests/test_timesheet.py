import unittest

from granary import timesheet


class Timesheet(unittest.TestCase):
    def test_sail_summary(self):
        self.assertEqual(timesheet.sail_summary(5, [0, 5, 10]), {'sail_summary': 2})
        self.assertEqual(timesheet.sail_summary(-1, [0, 5, 10]), {'sail_summary': 0})

    def test_top_n(self):
        self.assertEqual(timesheet.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(timesheet.top_n({'a': 1}, 5), ['a'])
