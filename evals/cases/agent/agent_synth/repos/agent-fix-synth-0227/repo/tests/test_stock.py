import unittest

from lantern import stock


class Stock(unittest.TestCase):
    def test_luhn_valid(self):
        self.assertEqual(stock.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(stock.luhn_valid('79927398713'), True)

    def test_running_total(self):
        self.assertEqual(stock.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(stock.running_total([]), [])

    def test_grade(self):
        self.assertEqual(stock.grade(95), 'A')
        self.assertEqual(stock.grade(90), 'A')
