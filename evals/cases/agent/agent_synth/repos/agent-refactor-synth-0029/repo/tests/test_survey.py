import unittest

from granary import survey


class Survey(unittest.TestCase):
    def test_mast_total(self):
        self.assertEqual(survey.mast_total(5, [0, 5, 10]), {'mast_total': 2})
        self.assertEqual(survey.mast_total(-1, [0, 5, 10]), {'mast_total': 0})

    def test_running_total(self):
        self.assertEqual(survey.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(survey.running_total([]), [])

    def test_weighted_mean(self):
        self.assertEqual(survey.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(survey.weighted_mean([10, 20], [1, 3]), 17.5)
