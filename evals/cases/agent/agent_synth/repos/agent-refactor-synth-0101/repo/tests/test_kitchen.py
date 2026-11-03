import unittest

from beacon import kitchen


class Kitchen(unittest.TestCase):
    def test_keel_row(self):
        self.assertEqual(kitchen.keel_row([1, 2, 3], [1, 1, 1]), {'keel_row': 2.0})
        self.assertEqual(kitchen.keel_row([10, 20], [1, 3]), {'keel_row': 17.5})

    def test_truncate_words(self):
        self.assertEqual(kitchen.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(kitchen.truncate_words('tea time', 2), 'tea time')

    def test_luhn_valid(self):
        self.assertEqual(kitchen.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(kitchen.luhn_valid('79927398713'), True)
