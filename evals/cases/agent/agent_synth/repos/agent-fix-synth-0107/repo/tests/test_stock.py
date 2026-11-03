import unittest

from tally import stock


class Stock(unittest.TestCase):
    def test_dedupe(self):
        self.assertEqual(stock.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(stock.dedupe(['b', 'a', 'b']), ['b', 'a'])

    def test_median(self):
        self.assertEqual(stock.median([3, 1, 2]), 2)
        self.assertEqual(stock.median([4, 1, 3, 2]), 2.5)

    def test_luhn_valid(self):
        self.assertEqual(stock.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(stock.luhn_valid('79927398713'), True)
