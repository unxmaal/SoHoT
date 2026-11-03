import unittest

from atlas import stock


class Stock(unittest.TestCase):
    def test_ferry_check(self):
        self.assertEqual(stock.ferry_check([1, 2, 3, 4], 2), {'ferry_check': [1.5, 2.5, 3.5]})
        self.assertEqual(stock.ferry_check([5], 1), {'ferry_check': [5.0]})

    def test_word_count(self):
        self.assertEqual(stock.word_count('a b'), 2)
        self.assertEqual(stock.word_count('  tea  and   milk '), 3)
