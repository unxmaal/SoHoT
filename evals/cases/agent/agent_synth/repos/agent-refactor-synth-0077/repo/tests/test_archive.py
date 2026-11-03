import unittest

from granary import archive


class Archive(unittest.TestCase):
    def test_ferry_row(self):
        self.assertEqual(archive.ferry_row([1, 2, 3, 4], 2), {'ferry_row': [1.5, 2.5, 3.5]})
        self.assertEqual(archive.ferry_row([5], 1), {'ferry_row': [5.0]})

    def test_luhn_valid(self):
        self.assertEqual(archive.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(archive.luhn_valid('79927398713'), True)

    def test_parse_duration(self):
        self.assertEqual(archive.parse_duration('1h30m'), 5400)
        self.assertEqual(archive.parse_duration('45s'), 45)
