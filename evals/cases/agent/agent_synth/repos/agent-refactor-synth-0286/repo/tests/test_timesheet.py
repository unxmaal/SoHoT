import unittest

from depot import timesheet


class Timesheet(unittest.TestCase):
    def test_keel_summary(self):
        self.assertEqual(timesheet.keel_summary([1, 2, 3], [1, 1, 1]), {'keel_summary': 2.0})
        self.assertEqual(timesheet.keel_summary([10, 20], [1, 3]), {'keel_summary': 17.5})

    def test_rle(self):
        self.assertEqual(timesheet.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(timesheet.rle(''), [])
