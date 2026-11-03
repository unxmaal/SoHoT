import unittest

from beacon import routes


class Routes(unittest.TestCase):
    def test_parse_duration(self):
        self.assertEqual(routes.parse_duration('1h30m'), 5400)
        self.assertEqual(routes.parse_duration('45s'), 45)

    def test_invert(self):
        self.assertEqual(routes.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(routes.invert({}), {})

    def test_luhn_valid(self):
        self.assertEqual(routes.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(routes.luhn_valid('79927398713'), True)
