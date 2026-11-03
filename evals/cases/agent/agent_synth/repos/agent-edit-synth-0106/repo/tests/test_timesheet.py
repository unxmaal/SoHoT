import unittest

from wharf import timesheet


class Timesheet(unittest.TestCase):
    def test_chunk(self):
        self.assertEqual(timesheet.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(timesheet.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(timesheet.chunk([], 3), [])

    def test_median(self):
        self.assertEqual(timesheet.median([3, 1, 2]), 2)
        self.assertEqual(timesheet.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(timesheet.median([5]), 5)
