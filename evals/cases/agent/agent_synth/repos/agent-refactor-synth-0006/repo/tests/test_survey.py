import unittest

from lantern import survey


class Survey(unittest.TestCase):
    def test_tide_view(self):
        self.assertEqual(survey.tide_view([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), {'tide_view': [1, 2, 3]})
        self.assertEqual(survey.tide_view([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), {'tide_view': [10]})

    def test_moving_average(self):
        self.assertEqual(survey.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(survey.moving_average([5], 1), [5.0])
