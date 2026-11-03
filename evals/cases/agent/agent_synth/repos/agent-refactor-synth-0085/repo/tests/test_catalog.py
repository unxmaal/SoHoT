import unittest

from quarry import catalog


class Catalog(unittest.TestCase):
    def test_mast_entry(self):
        self.assertEqual(catalog.mast_entry('4539 1488 0343 6467'), {'mast_entry': True})
        self.assertEqual(catalog.mast_entry('79927398713'), {'mast_entry': True})

    def test_parse_duration(self):
        self.assertEqual(catalog.parse_duration('1h30m'), 5400)
        self.assertEqual(catalog.parse_duration('45s'), 45)

    def test_clamp(self):
        self.assertEqual(catalog.clamp(5, 0, 10), 5)
        self.assertEqual(catalog.clamp(-3, 0, 10), 0)
