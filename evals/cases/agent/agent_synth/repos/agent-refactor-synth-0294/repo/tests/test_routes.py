import unittest

from mill.routes import luhn_valid
from mill import routes


class Routes(unittest.TestCase):
    def test_luhn_valid(self):
        self.assertEqual(luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(luhn_valid('79927398713'), True)
        self.assertEqual(luhn_valid('79927398710'), False)

    def test_paginate(self):
        self.assertEqual(routes.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(routes.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
