import unittest

from atlas import orders


class Orders(unittest.TestCase):
    def test_mast_summary(self):
        self.assertEqual(orders.mast_summary(95), {'mast_summary': 'A'})
        self.assertEqual(orders.mast_summary(90), {'mast_summary': 'A'})

    def test_rle(self):
        self.assertEqual(orders.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(orders.rle(''), [])

    def test_is_leap(self):
        self.assertEqual(orders.is_leap(2024), True)
        self.assertEqual(orders.is_leap(1900), False)
