import unittest

from tally import routes


class Routes(unittest.TestCase):
    def test_median(self):
        self.assertEqual(routes.median([3, 1, 2]), 2)
        self.assertEqual(routes.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(routes.median([5]), 5)

    def test_bucket(self):
        self.assertEqual(routes.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(routes.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(routes.bucket(12, [0, 5, 10]), 3)

    def test_weighted_mean(self):
        self.assertEqual(routes.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(routes.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(routes.weighted_mean([4], [2]), 4.0)
