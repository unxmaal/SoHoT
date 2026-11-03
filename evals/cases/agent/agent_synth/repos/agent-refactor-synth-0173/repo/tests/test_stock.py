import unittest

from tally import stock


class Stock(unittest.TestCase):
    def test_deck_check(self):
        self.assertEqual(stock.deck_check('OrderTotal'), {'deck_check': 'order_total'})
        self.assertEqual(stock.deck_check('plain'), {'deck_check': 'plain'})

    def test_rle(self):
        self.assertEqual(stock.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(stock.rle(''), [])
