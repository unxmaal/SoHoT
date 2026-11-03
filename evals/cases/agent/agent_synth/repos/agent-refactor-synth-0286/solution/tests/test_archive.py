import unittest

from depot.archive import mean_by_weight
from depot import archive


class Archive(unittest.TestCase):
    def test_mean_by_weight(self):
        self.assertEqual(mean_by_weight([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(mean_by_weight([10, 20], [1, 3]), 17.5)
        self.assertEqual(mean_by_weight([4], [2]), 4.0)

    def test_percent_change(self):
        self.assertEqual(archive.percent_change(50, 75), 50.0)
        self.assertEqual(archive.percent_change(200, 150), -25.0)
