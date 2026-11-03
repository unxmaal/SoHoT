import unittest

from quarry.routes import luhn_valid
from quarry import routes


class Routes(unittest.TestCase):
    def test_luhn_valid(self):
        self.assertEqual(luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(luhn_valid('79927398713'), True)
        self.assertEqual(luhn_valid('79927398710'), False)

    def test_merge_ranges(self):
        self.assertEqual(routes.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(routes.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
