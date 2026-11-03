import unittest

from depot import routes


class Routes(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(routes.clamp(5, 0, 10), 5)
        self.assertEqual(routes.clamp(-3, 0, 10), 0)

    def test_moving_average(self):
        self.assertEqual(routes.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(routes.moving_average([5], 1), [5.0])

    def test_median(self):
        self.assertEqual(routes.median([3, 1, 2]), 2)
        self.assertEqual(routes.median([4, 1, 3, 2]), 2.5)
