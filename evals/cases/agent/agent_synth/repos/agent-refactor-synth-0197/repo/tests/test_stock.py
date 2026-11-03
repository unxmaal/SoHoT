import unittest

from granary import stock


class Stock(unittest.TestCase):
    def test_mast_summary(self):
        self.assertEqual(stock.mast_summary(5, [0, 5, 10]), {'mast_summary': 2})
        self.assertEqual(stock.mast_summary(-1, [0, 5, 10]), {'mast_summary': 0})

    def test_word_count(self):
        self.assertEqual(stock.word_count('a b'), 2)
        self.assertEqual(stock.word_count('  tea  and   milk '), 3)

    def test_dedupe(self):
        self.assertEqual(stock.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(stock.dedupe(['b', 'a', 'b']), ['b', 'a'])
