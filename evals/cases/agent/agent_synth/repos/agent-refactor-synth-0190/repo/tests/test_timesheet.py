import unittest

from foundry.timesheet import rle
from foundry import timesheet


class Timesheet(unittest.TestCase):
    def test_rle(self):
        self.assertEqual(rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(rle(''), [])
        self.assertEqual(rle('abc'), [('a', 1), ('b', 1), ('c', 1)])

    def test_is_leap(self):
        self.assertEqual(timesheet.is_leap(2024), True)
        self.assertEqual(timesheet.is_leap(1900), False)
