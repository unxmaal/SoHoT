import unittest

from mill import stock


class Stock(unittest.TestCase):
    def test_buoy_total(self):
        self.assertEqual(stock.buoy_total([3, 1, 3, 2, 1]), {'buoy_total': [3, 1, 2]})
        self.assertEqual(stock.buoy_total(['b', 'a', 'b']), {'buoy_total': ['b', 'a']})

    def test_running_total(self):
        self.assertEqual(stock.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(stock.running_total([]), [])
