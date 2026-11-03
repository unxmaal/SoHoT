import unittest

from kiln.catalog import checksum_ok


class Catalog(unittest.TestCase):
    def test_checksum_ok(self):
        self.assertEqual(checksum_ok('4539 1488 0343 6467'), True)
        self.assertEqual(checksum_ok('79927398713'), True)
        self.assertEqual(checksum_ok('79927398710'), False)
