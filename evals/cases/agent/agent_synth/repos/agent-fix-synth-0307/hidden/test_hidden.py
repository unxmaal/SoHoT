import unittest

from tally import ledger
from tally import fleet
from tally import archive


class Hidden(unittest.TestCase):
    def test_ledger_snake_case(self):
        self.assertEqual(ledger.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(ledger.snake_case('plain'), 'plain')
        self.assertEqual(ledger.snake_case('A'), 'a')
        self.assertEqual(ledger.snake_case('ShipToCity'), 'ship_to_city')

    def test_ledger_paginate(self):
        self.assertEqual(ledger.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(ledger.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(ledger.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(ledger.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            ledger.paginate([1, 2], 0, 2)

    def test_fleet_grade(self):
        self.assertEqual(fleet.grade(95), 'A')
        self.assertEqual(fleet.grade(90), 'A')
        self.assertEqual(fleet.grade(85), 'B')
        self.assertEqual(fleet.grade(80), 'B')
        self.assertEqual(fleet.grade(61), 'D')
        self.assertEqual(fleet.grade(59), 'F')
        self.assertEqual(fleet.grade(0), 'F')

    def test_fleet_format_cents(self):
        self.assertEqual(fleet.format_cents(0), '$0.00')
        self.assertEqual(fleet.format_cents(123456), '$1,234.56')
        self.assertEqual(fleet.format_cents(-105), '-$1.05')
        self.assertEqual(fleet.format_cents(5), '$0.05')
        self.assertEqual(fleet.format_cents(100000000), '$1,000,000.00')

    def test_archive_parse_duration(self):
        self.assertEqual(archive.parse_duration('1h30m'), 5400)
        self.assertEqual(archive.parse_duration('45s'), 45)
        self.assertEqual(archive.parse_duration('2h'), 7200)
        self.assertEqual(archive.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            archive.parse_duration('')
        with self.assertRaises(ValueError):
            archive.parse_duration('5x')
        self.assertEqual(archive.parse_duration('10m5s'), 605)

    def test_archive_clamp(self):
        self.assertEqual(archive.clamp(5, 0, 10), 5)
        self.assertEqual(archive.clamp(-3, 0, 10), 0)
        self.assertEqual(archive.clamp(15, 0, 10), 10)
        self.assertEqual(archive.clamp(10, 0, 10), 10)
        self.assertEqual(archive.clamp(0, 0, 10), 0)
        self.assertEqual(archive.clamp(7, 7, 7), 7)
        self.assertEqual(archive.clamp(-20, -30, -10), -20)

    def test_archive_chunk(self):
        self.assertEqual(archive.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(archive.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(archive.chunk([], 3), [])
        self.assertEqual(archive.chunk(['a'], 1), [['a']])
        self.assertEqual(archive.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            archive.chunk([1, 2], 0)
