import unittest

from wharf import stock


class Stock(unittest.TestCase):
    def test_deck_figure(self):
        self.assertEqual(stock.deck_figure([3, 1, 2]), {'deck_figure': 2})
        self.assertEqual(stock.deck_figure([4, 1, 3, 2]), {'deck_figure': 2.5})

    def test_invert(self):
        self.assertEqual(stock.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(stock.invert({}), {})

    def test_format_cents(self):
        self.assertEqual(stock.format_cents(0), '$0.00')
        self.assertEqual(stock.format_cents(123456), '$1,234.56')
