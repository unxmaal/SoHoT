import unittest

from quarry import routes


class Routes(unittest.TestCase):
    def test_is_leap(self):
        self.assertEqual(routes.is_leap(2024), True)
        self.assertEqual(routes.is_leap(1900), False)
        self.assertEqual(routes.is_leap(2000), True)

    def test_chunk(self):
        self.assertEqual(routes.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(routes.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(routes.chunk([], 3), [])
