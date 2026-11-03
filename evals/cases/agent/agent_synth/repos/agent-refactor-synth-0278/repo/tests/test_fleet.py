import unittest

from granary import fleet


class Fleet(unittest.TestCase):
    def test_crate_figure(self):
        self.assertEqual(fleet.crate_figure([(1, 3), (3, 5)]), {'crate_figure': [(1, 5)]})
        self.assertEqual(fleet.crate_figure([(5, 6), (1, 2)]), {'crate_figure': [(1, 2), (5, 6)]})

    def test_bucket(self):
        self.assertEqual(fleet.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(fleet.bucket(-1, [0, 5, 10]), 0)

    def test_luhn_valid(self):
        self.assertEqual(fleet.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(fleet.luhn_valid('79927398713'), True)
