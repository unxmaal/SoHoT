import unittest

from beacon import archive


class Archive(unittest.TestCase):
    def test_dedupe(self):
        self.assertEqual(archive.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(archive.dedupe(['b', 'a', 'b']), ['b', 'a'])

    def test_format_cents(self):
        self.assertEqual(archive.format_cents(0), '$0.00')
        self.assertEqual(archive.format_cents(123456), '$1,234.56')

    def test_clamp(self):
        self.assertEqual(archive.clamp(5, 0, 10), 5)
        self.assertEqual(archive.clamp(-3, 0, 10), 0)
