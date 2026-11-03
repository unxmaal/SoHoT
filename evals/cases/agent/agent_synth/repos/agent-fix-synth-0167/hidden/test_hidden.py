import unittest

from atlas import shipping
from atlas import fleet
from atlas import stock
from atlas import digest


class Hidden(unittest.TestCase):
    def test_shipping_dedupe(self):
        self.assertEqual(shipping.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(shipping.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(shipping.dedupe([]), [])
        self.assertEqual(shipping.dedupe([1, 1, 1]), [1])

    def test_shipping_clamp(self):
        self.assertEqual(shipping.clamp(5, 0, 10), 5)
        self.assertEqual(shipping.clamp(-3, 0, 10), 0)
        self.assertEqual(shipping.clamp(15, 0, 10), 10)
        self.assertEqual(shipping.clamp(10, 0, 10), 10)
        self.assertEqual(shipping.clamp(0, 0, 10), 0)
        self.assertEqual(shipping.clamp(7, 7, 7), 7)
        self.assertEqual(shipping.clamp(-20, -30, -10), -20)

    def test_shipping_snake_case(self):
        self.assertEqual(shipping.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(shipping.snake_case('plain'), 'plain')
        self.assertEqual(shipping.snake_case('A'), 'a')
        self.assertEqual(shipping.snake_case('ShipToCity'), 'ship_to_city')

    def test_fleet_running_total(self):
        self.assertEqual(fleet.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(fleet.running_total([]), [])
        self.assertEqual(fleet.running_total([5]), [5])
        self.assertEqual(fleet.running_total([2, -2, 2]), [2, 0, 2])

    def test_fleet_merge_ranges(self):
        self.assertEqual(fleet.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(fleet.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(fleet.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(fleet.merge_ranges([]), [])
        self.assertEqual(fleet.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_fleet_moving_average(self):
        self.assertEqual(fleet.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(fleet.moving_average([5], 1), [5.0])
        self.assertEqual(fleet.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(fleet.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            fleet.moving_average([1, 2], 0)

    def test_stock_is_leap(self):
        self.assertEqual(stock.is_leap(2024), True)
        self.assertEqual(stock.is_leap(1900), False)
        self.assertEqual(stock.is_leap(2000), True)
        self.assertEqual(stock.is_leap(2023), False)
        self.assertEqual(stock.is_leap(2400), True)
        self.assertEqual(stock.is_leap(2100), False)

    def test_stock_bucket(self):
        self.assertEqual(stock.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(stock.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(stock.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(stock.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(stock.bucket(7, []), 0)

    def test_digest_quay_check(self):
        self.assertEqual(digest.quay_check([3, 1, 3, 2, 1]), {'quay_check': [3, 1, 2]})
        self.assertEqual(digest.quay_check(['b', 'a', 'b']), {'quay_check': ['b', 'a']})
        self.assertEqual(digest.quay_check([]), {'quay_check': []})
        self.assertEqual(digest.quay_check([1, 1, 1]), {'quay_check': [1]})

    def test_digest_berth_total(self):
        self.assertEqual(digest.berth_total(5, 0, 10), {'berth_total': 5})
        self.assertEqual(digest.berth_total(-3, 0, 10), {'berth_total': 0})
        self.assertEqual(digest.berth_total(15, 0, 10), {'berth_total': 10})
        self.assertEqual(digest.berth_total(10, 0, 10), {'berth_total': 10})
        self.assertEqual(digest.berth_total(0, 0, 10), {'berth_total': 0})
        self.assertEqual(digest.berth_total(7, 7, 7), {'berth_total': 7})
        self.assertEqual(digest.berth_total(-20, -30, -10), {'berth_total': -20})

    def test_digest_hull_check(self):
        self.assertEqual(digest.hull_check('OrderTotal'), {'hull_check': 'order_total'})
        self.assertEqual(digest.hull_check('plain'), {'hull_check': 'plain'})
        self.assertEqual(digest.hull_check('A'), {'hull_check': 'a'})
        self.assertEqual(digest.hull_check('ShipToCity'), {'hull_check': 'ship_to_city'})

    def test_digest_crate_summary(self):
        self.assertEqual(digest.crate_summary([1, 2, 3]), {'crate_summary': [1, 3, 6]})
        self.assertEqual(digest.crate_summary([]), {'crate_summary': []})
        self.assertEqual(digest.crate_summary([5]), {'crate_summary': [5]})
        self.assertEqual(digest.crate_summary([2, -2, 2]), {'crate_summary': [2, 0, 2]})

    def test_digest_buoy_row(self):
        self.assertEqual(digest.buoy_row([1, 2, 3, 4], 2), {'buoy_row': [1.5, 2.5, 3.5]})
        self.assertEqual(digest.buoy_row([5], 1), {'buoy_row': [5.0]})
        self.assertEqual(digest.buoy_row([1, 2, 3], 3), {'buoy_row': [2.0]})
        self.assertEqual(digest.buoy_row([2, 4, 6, 8, 10], 3), {'buoy_row': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            digest.buoy_row([1, 2], 0)
