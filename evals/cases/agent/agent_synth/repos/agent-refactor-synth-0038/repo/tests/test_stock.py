import unittest

from granary import stock


class Stock(unittest.TestCase):
    def test_keel_summary(self):
        self.assertEqual(stock.keel_summary('a b'), {'keel_summary': 2})
        self.assertEqual(stock.keel_summary('  tea  and   milk '), {'keel_summary': 3})

    def test_luhn_valid(self):
        self.assertEqual(stock.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(stock.luhn_valid('79927398713'), True)

    def test_invert(self):
        self.assertEqual(stock.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(stock.invert({}), {})
