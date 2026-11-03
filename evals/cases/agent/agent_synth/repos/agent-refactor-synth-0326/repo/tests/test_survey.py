import unittest

from kiln import survey


class Survey(unittest.TestCase):
    def test_harbor_line(self):
        self.assertEqual(survey.harbor_line('the quick brown fox', 2), {'harbor_line': 'the quick...'})
        self.assertEqual(survey.harbor_line('tea time', 2), {'harbor_line': 'tea time'})

    def test_moving_average(self):
        self.assertEqual(survey.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(survey.moving_average([5], 1), [5.0])

    def test_median(self):
        self.assertEqual(survey.median([3, 1, 2]), 2)
        self.assertEqual(survey.median([4, 1, 3, 2]), 2.5)
