import unittest

from harbor.survey import weighted_mean
from harbor import survey


class Survey(unittest.TestCase):
    def test_weighted_mean(self):
        self.assertEqual(weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(weighted_mean([4], [2]), 4.0)

    def test_running_total(self):
        self.assertEqual(survey.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(survey.running_total([]), [])
