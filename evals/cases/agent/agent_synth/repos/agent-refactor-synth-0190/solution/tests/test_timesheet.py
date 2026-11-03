import unittest

from foundry.timesheet import encode_runs
from foundry import timesheet


class Timesheet(unittest.TestCase):
    def test_encode_runs(self):
        self.assertEqual(encode_runs('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(encode_runs(''), [])
        self.assertEqual(encode_runs('abc'), [('a', 1), ('b', 1), ('c', 1)])

    def test_is_leap(self):
        self.assertEqual(timesheet.is_leap(2024), True)
        self.assertEqual(timesheet.is_leap(1900), False)
