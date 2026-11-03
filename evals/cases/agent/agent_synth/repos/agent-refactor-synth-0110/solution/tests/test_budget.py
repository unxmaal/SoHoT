import unittest

from depot.budget import weighted_average


class Budget(unittest.TestCase):
    def test_weighted_average(self):
        self.assertEqual(weighted_average([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(weighted_average([10, 20], [1, 3]), 17.5)
        self.assertEqual(weighted_average([4], [2]), 4.0)
