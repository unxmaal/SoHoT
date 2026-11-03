import unittest

from lantern.routes import moving_average


class Routes(unittest.TestCase):
    def test_moving_average(self):
        self.assertEqual(moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(moving_average([5], 1), [5.0])
        self.assertEqual(moving_average([1, 2, 3], 3), [2.0])
