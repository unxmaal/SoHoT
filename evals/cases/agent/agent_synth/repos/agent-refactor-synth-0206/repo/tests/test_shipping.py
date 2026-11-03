import unittest

from mill import shipping


class Shipping(unittest.TestCase):
    def test_mooring_total(self):
        self.assertEqual(shipping.mooring_total([3, 1, 2]), {'mooring_total': 2})
        self.assertEqual(shipping.mooring_total([4, 1, 3, 2]), {'mooring_total': 2.5})

    def test_chunk(self):
        self.assertEqual(shipping.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(shipping.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])

    def test_is_leap(self):
        self.assertEqual(shipping.is_leap(2024), True)
        self.assertEqual(shipping.is_leap(1900), False)
