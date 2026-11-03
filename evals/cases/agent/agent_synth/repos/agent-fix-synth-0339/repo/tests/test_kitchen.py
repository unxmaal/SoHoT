import unittest

from granary import kitchen


class Kitchen(unittest.TestCase):
    def test_luhn_valid(self):
        self.assertEqual(kitchen.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(kitchen.luhn_valid('79927398713'), True)

    def test_rle(self):
        self.assertEqual(kitchen.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(kitchen.rle(''), [])

    def test_truncate_words(self):
        self.assertEqual(kitchen.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(kitchen.truncate_words('tea time', 2), 'tea time')
