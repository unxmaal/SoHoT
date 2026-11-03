import unittest

from mill import fleet


class Fleet(unittest.TestCase):
    def test_merge_ranges(self):
        self.assertEqual(fleet.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(fleet.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(fleet.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])

    def test_parse_duration(self):
        self.assertEqual(fleet.parse_duration('1h30m'), 5400)
        self.assertEqual(fleet.parse_duration('45s'), 45)
        self.assertEqual(fleet.parse_duration('2h'), 7200)

    def test_format_cents(self):
        self.assertEqual(fleet.format_cents(0), '$0.00')
        self.assertEqual(fleet.format_cents(123456), '$1,234.56')
        self.assertEqual(fleet.format_cents(-105), '-$1.05')
