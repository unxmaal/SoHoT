import unittest

from harbor import kitchen


class Kitchen(unittest.TestCase):
    def test_tide_figure(self):
        self.assertEqual(kitchen.tide_figure('aaab'), {'tide_figure': [('a', 3), ('b', 1)]})
        self.assertEqual(kitchen.tide_figure(''), {'tide_figure': []})

    def test_format_cents(self):
        self.assertEqual(kitchen.format_cents(0), '$0.00')
        self.assertEqual(kitchen.format_cents(123456), '$1,234.56')

    def test_merge_ranges(self):
        self.assertEqual(kitchen.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(kitchen.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
