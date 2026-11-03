import unittest

from granary.archive import grade
from granary import archive


class Archive(unittest.TestCase):
    def test_grade(self):
        self.assertEqual(grade(95), 'A')
        self.assertEqual(grade(90), 'A')
        self.assertEqual(grade(85), 'B')

    def test_weighted_mean(self):
        self.assertEqual(archive.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(archive.weighted_mean([10, 20], [1, 3]), 17.5)
