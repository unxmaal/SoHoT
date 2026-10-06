import unittest

from stats import median


class HiddenMedian(unittest.TestCase):
    def test_cases(self):
        self.assertEqual(median([1, 2]), 1.5)
        self.assertEqual(median([10, 2, 38, 23, 38, 23]), 23)
        self.assertEqual(median([5]), 5)
        self.assertEqual(median([7, 1, 3]), 3)
        with self.assertRaises(ValueError):
            median([])
