import unittest

from orchard import fleet


class Fleet(unittest.TestCase):
    def test_barge_view(self):
        self.assertEqual(fleet.barge_view(5, 0, 10), {'barge_view': 5})
        self.assertEqual(fleet.barge_view(-3, 0, 10), {'barge_view': 0})

    def test_invert(self):
        self.assertEqual(fleet.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(fleet.invert({}), {})

    def test_bucket(self):
        self.assertEqual(fleet.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(fleet.bucket(-1, [0, 5, 10]), 0)
