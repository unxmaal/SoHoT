import unittest

from compass import timesheet


class Timesheet(unittest.TestCase):
    def test_lantern_view(self):
        self.assertEqual(timesheet.lantern_view(95), {'lantern_view': 'A'})
        self.assertEqual(timesheet.lantern_view(90), {'lantern_view': 'A'})

    def test_moving_average(self):
        self.assertEqual(timesheet.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(timesheet.moving_average([5], 1), [5.0])

    def test_weighted_mean(self):
        self.assertEqual(timesheet.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(timesheet.weighted_mean([10, 20], [1, 3]), 17.5)
