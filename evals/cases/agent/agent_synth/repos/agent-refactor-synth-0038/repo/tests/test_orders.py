import unittest

from granary import orders


class Orders(unittest.TestCase):
    def test_buoy_summary(self):
        self.assertEqual(orders.buoy_summary('a b'), {'buoy_summary': 2})
        self.assertEqual(orders.buoy_summary('  tea  and   milk '), {'buoy_summary': 3})

    def test_running_total(self):
        self.assertEqual(orders.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(orders.running_total([]), [])
