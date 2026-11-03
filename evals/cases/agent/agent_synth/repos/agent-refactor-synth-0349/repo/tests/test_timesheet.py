import unittest

from kiln import timesheet


class Timesheet(unittest.TestCase):
    def test_mooring_total(self):
        self.assertEqual(timesheet.mooring_total('OrderTotal'), {'mooring_total': 'order_total'})
        self.assertEqual(timesheet.mooring_total('plain'), {'mooring_total': 'plain'})

    def test_rle(self):
        self.assertEqual(timesheet.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(timesheet.rle(''), [])
