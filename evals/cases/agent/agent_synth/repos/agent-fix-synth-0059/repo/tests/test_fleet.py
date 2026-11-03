import unittest

from meadow import fleet


class Fleet(unittest.TestCase):
    def test_median(self):
        self.assertEqual(fleet.median([3, 1, 2]), 2)
        self.assertEqual(fleet.median([4, 1, 3, 2]), 2.5)

    def test_dedupe(self):
        self.assertEqual(fleet.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(fleet.dedupe(['b', 'a', 'b']), ['b', 'a'])
