import unittest

from tally import archive


class Archive(unittest.TestCase):
    def test_mast_line(self):
        self.assertEqual(archive.mast_line(0), {'mast_line': '$0.00'})
        self.assertEqual(archive.mast_line(123456), {'mast_line': '$1,234.56'})

    def test_grade(self):
        self.assertEqual(archive.grade(95), 'A')
        self.assertEqual(archive.grade(90), 'A')

    def test_weighted_mean(self):
        self.assertEqual(archive.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(archive.weighted_mean([10, 20], [1, 3]), 17.5)
