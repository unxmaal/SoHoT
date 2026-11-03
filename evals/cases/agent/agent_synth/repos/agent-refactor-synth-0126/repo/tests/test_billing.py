import unittest

from compass import billing


class Billing(unittest.TestCase):
    def test_buoy_total(self):
        self.assertEqual(billing.buoy_total(0), {'buoy_total': '$0.00'})
        self.assertEqual(billing.buoy_total(123456), {'buoy_total': '$1,234.56'})

    def test_rle(self):
        self.assertEqual(billing.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(billing.rle(''), [])
