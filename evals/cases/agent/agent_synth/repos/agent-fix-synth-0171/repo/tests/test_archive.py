import unittest

from lantern import archive


class Archive(unittest.TestCase):
    def test_invert(self):
        self.assertEqual(archive.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(archive.invert({}), {})

    def test_top_n(self):
        self.assertEqual(archive.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(archive.top_n({'a': 1}, 5), ['a'])

    def test_weighted_mean(self):
        self.assertEqual(archive.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(archive.weighted_mean([10, 20], [1, 3]), 17.5)
