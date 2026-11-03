import unittest

from granary import stock


class Stock(unittest.TestCase):
    def test_median(self):
        self.assertEqual(stock.median([3, 1, 2]), 2)
        self.assertEqual(stock.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(stock.median([5]), 5)

    def test_dedupe(self):
        self.assertEqual(stock.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(stock.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(stock.dedupe([]), [])
