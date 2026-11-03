import unittest

from atlas import archive


class Archive(unittest.TestCase):
    def test_luhn_valid(self):
        self.assertEqual(archive.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(archive.luhn_valid('79927398713'), True)

    def test_dedupe(self):
        self.assertEqual(archive.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(archive.dedupe(['b', 'a', 'b']), ['b', 'a'])
