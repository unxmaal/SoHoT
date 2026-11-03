import unittest

from wharf.textual import merge_ranges
from wharf import stock


class Stock(unittest.TestCase):
    def test_merge_ranges(self):
        self.assertEqual(merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(merge_ranges([(1, 10), (2, 3)]), [(1, 10)])

    def test_parse_duration(self):
        self.assertEqual(stock.parse_duration('1h30m'), 5400)
        self.assertEqual(stock.parse_duration('45s'), 45)
