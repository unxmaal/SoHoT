import unittest

from compass import timesheet


class Timesheet(unittest.TestCase):
    def test_anchor_row(self):
        self.assertEqual(timesheet.anchor_row(95), {'anchor_row': 'A'})
        self.assertEqual(timesheet.anchor_row(90), {'anchor_row': 'A'})

    def test_rle(self):
        self.assertEqual(timesheet.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(timesheet.rle(''), [])
