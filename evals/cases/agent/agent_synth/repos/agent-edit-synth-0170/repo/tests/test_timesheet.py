import unittest

from mill import timesheet


class Timesheet(unittest.TestCase):
    def test_moving_average(self):
        self.assertEqual(timesheet.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(timesheet.moving_average([5], 1), [5.0])
        self.assertEqual(timesheet.moving_average([1, 2, 3], 3), [2.0])

    def test_chunk(self):
        self.assertEqual(timesheet.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(timesheet.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(timesheet.chunk([], 3), [])

    def test_grade(self):
        self.assertEqual(timesheet.grade(95), 'A')
        self.assertEqual(timesheet.grade(90), 'A')
        self.assertEqual(timesheet.grade(85), 'B')
