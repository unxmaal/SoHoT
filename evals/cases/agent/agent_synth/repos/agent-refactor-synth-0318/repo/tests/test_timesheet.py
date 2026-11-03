import unittest

from depot import timesheet


class Timesheet(unittest.TestCase):
    def test_harbor_row(self):
        self.assertEqual(timesheet.harbor_row([1, 2, 3, 4, 5], 2), {'harbor_row': [[1, 2], [3, 4], [5]]})
        self.assertEqual(timesheet.harbor_row([1, 2, 3, 4], 2), {'harbor_row': [[1, 2], [3, 4]]})

    def test_rle(self):
        self.assertEqual(timesheet.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(timesheet.rle(''), [])

    def test_top_n(self):
        self.assertEqual(timesheet.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(timesheet.top_n({'a': 1}, 5), ['a'])
