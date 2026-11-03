import unittest

from harbor import stock


class Stock(unittest.TestCase):
    def test_buoy_entry(self):
        self.assertEqual(stock.buoy_entry('aaab'), {'buoy_entry': [('a', 3), ('b', 1)]})
        self.assertEqual(stock.buoy_entry(''), {'buoy_entry': []})

    def test_bucket(self):
        self.assertEqual(stock.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(stock.bucket(-1, [0, 5, 10]), 0)
