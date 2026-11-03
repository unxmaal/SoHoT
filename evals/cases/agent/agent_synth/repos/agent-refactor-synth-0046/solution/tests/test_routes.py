import unittest

from kiln.routes import window_means


class Routes(unittest.TestCase):
    def test_window_means(self):
        self.assertEqual(window_means([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(window_means([5], 1), [5.0])
        self.assertEqual(window_means([1, 2, 3], 3), [2.0])
