import unittest

from harbor import survey


class Survey(unittest.TestCase):
    def test_percent_change(self):
        self.assertEqual(survey.percent_change(50, 75), 50.0)
        self.assertEqual(survey.percent_change(200, 150), -25.0)

    def test_moving_average(self):
        self.assertEqual(survey.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(survey.moving_average([5], 1), [5.0])

    def test_merge_ranges(self):
        self.assertEqual(survey.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(survey.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
