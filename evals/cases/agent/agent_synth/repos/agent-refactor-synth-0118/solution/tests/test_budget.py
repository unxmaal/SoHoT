import unittest

from kiln.budget import coalesce


class Budget(unittest.TestCase):
    def test_coalesce(self):
        self.assertEqual(coalesce([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(coalesce([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(coalesce([(1, 10), (2, 3)]), [(1, 10)])
