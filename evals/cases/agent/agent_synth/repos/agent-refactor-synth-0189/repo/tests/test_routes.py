import unittest

from tally import routes


class Routes(unittest.TestCase):
    def test_pallet_summary(self):
        self.assertEqual(routes.pallet_summary([1, 2, 3, 4], 2), {'pallet_summary': [1.5, 2.5, 3.5]})
        self.assertEqual(routes.pallet_summary([5], 1), {'pallet_summary': [5.0]})

    def test_luhn_valid(self):
        self.assertEqual(routes.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(routes.luhn_valid('79927398713'), True)
