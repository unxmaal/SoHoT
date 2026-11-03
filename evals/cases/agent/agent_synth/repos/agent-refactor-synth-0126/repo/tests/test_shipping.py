import unittest

from compass import shipping


class Shipping(unittest.TestCase):
    def test_pallet_view(self):
        self.assertEqual(shipping.pallet_view(0), {'pallet_view': '$0.00'})
        self.assertEqual(shipping.pallet_view(123456), {'pallet_view': '$1,234.56'})

    def test_grade(self):
        self.assertEqual(shipping.grade(95), 'A')
        self.assertEqual(shipping.grade(90), 'A')
