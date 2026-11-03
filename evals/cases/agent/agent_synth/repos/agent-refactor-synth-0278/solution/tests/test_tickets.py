import unittest

from granary.tickets import join_ranges


class Tickets(unittest.TestCase):
    def test_join_ranges(self):
        self.assertEqual(join_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(join_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(join_ranges([(1, 10), (2, 3)]), [(1, 10)])
