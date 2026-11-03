import unittest

from harbor import timesheet


class Timesheet(unittest.TestCase):
    def test_dedupe(self):
        self.assertEqual(timesheet.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(timesheet.dedupe(['b', 'a', 'b']), ['b', 'a'])

    def test_rle(self):
        self.assertEqual(timesheet.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(timesheet.rle(''), [])
