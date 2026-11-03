import unittest

from quarry.stock import running_total
from quarry import stock


class Stock(unittest.TestCase):
    def test_running_total(self):
        self.assertEqual(running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(running_total([]), [])
        self.assertEqual(running_total([5]), [5])

    def test_parse_duration(self):
        self.assertEqual(stock.parse_duration('1h30m'), 5400)
        self.assertEqual(stock.parse_duration('45s'), 45)
