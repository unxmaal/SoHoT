import unittest

from atlas import archive


class Archive(unittest.TestCase):
    def test_quay_check(self):
        self.assertEqual(archive.quay_check(95), {'quay_check': 'A'})
        self.assertEqual(archive.quay_check(90), {'quay_check': 'A'})

    def test_median(self):
        self.assertEqual(archive.median([3, 1, 2]), 2)
        self.assertEqual(archive.median([4, 1, 3, 2]), 2.5)

    def test_moving_average(self):
        self.assertEqual(archive.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(archive.moving_average([5], 1), [5.0])
