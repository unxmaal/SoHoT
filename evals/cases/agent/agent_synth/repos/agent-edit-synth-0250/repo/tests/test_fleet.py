import unittest

from wharf import fleet


class Fleet(unittest.TestCase):
    def test_dedupe(self):
        self.assertEqual(fleet.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(fleet.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(fleet.dedupe([]), [])

    def test_bucket(self):
        self.assertEqual(fleet.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(fleet.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(fleet.bucket(12, [0, 5, 10]), 3)
