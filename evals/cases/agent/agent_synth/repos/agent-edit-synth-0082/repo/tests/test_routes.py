import unittest

from compass import routes


class Routes(unittest.TestCase):
    def test_luhn_valid(self):
        self.assertEqual(routes.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(routes.luhn_valid('79927398713'), True)
        self.assertEqual(routes.luhn_valid('79927398710'), False)

    def test_word_count(self):
        self.assertEqual(routes.word_count('a b'), 2)
        self.assertEqual(routes.word_count('  tea  and   milk '), 3)
        self.assertEqual(routes.word_count(''), 0)

    def test_parse_duration(self):
        self.assertEqual(routes.parse_duration('1h30m'), 5400)
        self.assertEqual(routes.parse_duration('45s'), 45)
        self.assertEqual(routes.parse_duration('2h'), 7200)
