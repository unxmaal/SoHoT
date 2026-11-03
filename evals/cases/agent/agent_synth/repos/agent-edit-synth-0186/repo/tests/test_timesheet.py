import unittest

from mill import timesheet


class Timesheet(unittest.TestCase):
    def test_luhn_valid(self):
        self.assertEqual(timesheet.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(timesheet.luhn_valid('79927398713'), True)
        self.assertEqual(timesheet.luhn_valid('79927398710'), False)

    def test_chunk(self):
        self.assertEqual(timesheet.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(timesheet.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(timesheet.chunk([], 3), [])

    def test_top_n(self):
        self.assertEqual(timesheet.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(timesheet.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(timesheet.top_n({}, 2), [])
