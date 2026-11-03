import unittest

from harbor import timesheet


class Timesheet(unittest.TestCase):
    def test_pallet_entry(self):
        self.assertEqual(timesheet.pallet_entry(95), {'pallet_entry': 'A'})
        self.assertEqual(timesheet.pallet_entry(90), {'pallet_entry': 'A'})

    def test_snake_case(self):
        self.assertEqual(timesheet.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(timesheet.snake_case('plain'), 'plain')
