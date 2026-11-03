import unittest

from mill import stock


class Stock(unittest.TestCase):
    def test_is_leap(self):
        self.assertEqual(stock.is_leap(2024), True)
        self.assertEqual(stock.is_leap(1900), False)
        self.assertEqual(stock.is_leap(2000), True)

    def test_percent_change(self):
        self.assertEqual(stock.percent_change(50, 75), 50.0)
        self.assertEqual(stock.percent_change(200, 150), -25.0)
        self.assertEqual(stock.percent_change(80, 80), 0.0)

    def test_word_count(self):
        self.assertEqual(stock.word_count('a b'), 2)
        self.assertEqual(stock.word_count('  tea  and   milk '), 3)
        self.assertEqual(stock.word_count(''), 0)
