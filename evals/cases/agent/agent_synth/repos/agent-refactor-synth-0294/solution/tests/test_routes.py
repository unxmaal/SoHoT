import unittest

from mill.routes import checksum_ok
from mill import routes


class Routes(unittest.TestCase):
    def test_checksum_ok(self):
        self.assertEqual(checksum_ok('4539 1488 0343 6467'), True)
        self.assertEqual(checksum_ok('79927398713'), True)
        self.assertEqual(checksum_ok('79927398710'), False)

    def test_paginate(self):
        self.assertEqual(routes.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(routes.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
