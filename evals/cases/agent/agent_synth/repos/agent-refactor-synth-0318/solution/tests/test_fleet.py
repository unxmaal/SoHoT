import unittest

from depot.fleet import batches


class Fleet(unittest.TestCase):
    def test_batches(self):
        self.assertEqual(batches([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(batches([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(batches([], 3), [])
