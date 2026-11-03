import unittest

from depot.budget import weighted_mean


class Budget(unittest.TestCase):
    def test_weighted_mean(self):
        self.assertEqual(weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(weighted_mean([4], [2]), 4.0)
