import unittest

from meadow import stock


class Stock(unittest.TestCase):
    def test_quay_summary(self):
        self.assertEqual(stock.quay_summary(5, [0, 5, 10]), {'quay_summary': 2})
        self.assertEqual(stock.quay_summary(-1, [0, 5, 10]), {'quay_summary': 0})

    def test_dedupe(self):
        self.assertEqual(stock.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(stock.dedupe(['b', 'a', 'b']), ['b', 'a'])
