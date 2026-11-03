import unittest

from quarry import budget
from quarry import archive
from quarry import catalog


class Hidden(unittest.TestCase):
    def test_budget_clamp(self):
        self.assertEqual(budget.clamp(5, 0, 10), 5)
        self.assertEqual(budget.clamp(-3, 0, 10), 0)
        self.assertEqual(budget.clamp(15, 0, 10), 10)
        self.assertEqual(budget.clamp(10, 0, 10), 10)
        self.assertEqual(budget.clamp(0, 0, 10), 0)
        self.assertEqual(budget.clamp(7, 7, 7), 7)
        self.assertEqual(budget.clamp(-20, -30, -10), -20)

    def test_budget_is_leap(self):
        self.assertEqual(budget.is_leap(2024), True)
        self.assertEqual(budget.is_leap(1900), False)
        self.assertEqual(budget.is_leap(2000), True)
        self.assertEqual(budget.is_leap(2023), False)
        self.assertEqual(budget.is_leap(2400), True)
        self.assertEqual(budget.is_leap(2100), False)

    def test_budget_percent_change(self):
        self.assertEqual(budget.percent_change(50, 75), 50.0)
        self.assertEqual(budget.percent_change(200, 150), -25.0)
        self.assertEqual(budget.percent_change(80, 80), 0.0)
        self.assertEqual(budget.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            budget.percent_change(0, 5)
        self.assertEqual(budget.percent_change(-10, -5), -50.0)

    def test_archive_running_total(self):
        self.assertEqual(archive.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(archive.running_total([]), [])
        self.assertEqual(archive.running_total([5]), [5])
        self.assertEqual(archive.running_total([2, -2, 2]), [2, 0, 2])

    def test_archive_chunk(self):
        self.assertEqual(archive.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(archive.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(archive.chunk([], 3), [])
        self.assertEqual(archive.chunk(['a'], 1), [['a']])
        self.assertEqual(archive.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            archive.chunk([1, 2], 0)

    def test_archive_truncate_words(self):
        self.assertEqual(archive.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(archive.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(archive.truncate_words('', 3), '')
        self.assertEqual(archive.truncate_words('one two three', 1), 'one...')

    def test_catalog_format_cents(self):
        self.assertEqual(catalog.format_cents(0), '$0.00')
        self.assertEqual(catalog.format_cents(123456), '$1,234.56')
        self.assertEqual(catalog.format_cents(-105), '-$1.05')
        self.assertEqual(catalog.format_cents(5), '$0.05')
        self.assertEqual(catalog.format_cents(100000000), '$1,000,000.00')

    def test_catalog_rle(self):
        self.assertEqual(catalog.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(catalog.rle(''), [])
        self.assertEqual(catalog.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(catalog.rle('zz'), [('z', 2)])

    def test_feature(self):
        self.assertEqual(archive.running_total([1, 2], start=10), [11, 13])
        self.assertEqual(archive.running_total([], start=4), [])
        self.assertEqual(archive.running_total([3], start=-3), [0])
