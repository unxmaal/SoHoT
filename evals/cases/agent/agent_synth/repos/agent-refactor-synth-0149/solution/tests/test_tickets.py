import unittest

from compass.core_math import merge_ranges
from compass import tickets


class Tickets(unittest.TestCase):
    def test_merge_ranges(self):
        self.assertEqual(merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(merge_ranges([(1, 10), (2, 3)]), [(1, 10)])

    def test_percent_change(self):
        self.assertEqual(tickets.percent_change(50, 75), 50.0)
        self.assertEqual(tickets.percent_change(200, 150), -25.0)
