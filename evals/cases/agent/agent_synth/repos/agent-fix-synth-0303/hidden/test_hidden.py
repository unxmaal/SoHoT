import unittest

from wharf import shipping
from wharf import orders
from wharf import ledger
from wharf import routes
from wharf import digest


class Hidden(unittest.TestCase):
    def test_shipping_clamp(self):
        self.assertEqual(shipping.clamp(5, 0, 10), 5)
        self.assertEqual(shipping.clamp(-3, 0, 10), 0)
        self.assertEqual(shipping.clamp(15, 0, 10), 10)
        self.assertEqual(shipping.clamp(10, 0, 10), 10)
        self.assertEqual(shipping.clamp(0, 0, 10), 0)
        self.assertEqual(shipping.clamp(7, 7, 7), 7)
        self.assertEqual(shipping.clamp(-20, -30, -10), -20)

    def test_shipping_luhn_valid(self):
        self.assertEqual(shipping.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(shipping.luhn_valid('79927398713'), True)
        self.assertEqual(shipping.luhn_valid('79927398710'), False)
        self.assertEqual(shipping.luhn_valid(''), False)
        self.assertEqual(shipping.luhn_valid('059'), True)

    def test_shipping_grade(self):
        self.assertEqual(shipping.grade(95), 'A')
        self.assertEqual(shipping.grade(90), 'A')
        self.assertEqual(shipping.grade(85), 'B')
        self.assertEqual(shipping.grade(80), 'B')
        self.assertEqual(shipping.grade(61), 'D')
        self.assertEqual(shipping.grade(59), 'F')
        self.assertEqual(shipping.grade(0), 'F')

    def test_orders_truncate_words(self):
        self.assertEqual(orders.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(orders.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(orders.truncate_words('', 3), '')
        self.assertEqual(orders.truncate_words('one two three', 1), 'one...')

    def test_orders_median(self):
        self.assertEqual(orders.median([3, 1, 2]), 2)
        self.assertEqual(orders.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(orders.median([5]), 5)
        self.assertEqual(orders.median([1, 2]), 1.5)
        self.assertEqual(orders.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            orders.median([])

    def test_ledger_is_leap(self):
        self.assertEqual(ledger.is_leap(2024), True)
        self.assertEqual(ledger.is_leap(1900), False)
        self.assertEqual(ledger.is_leap(2000), True)
        self.assertEqual(ledger.is_leap(2023), False)
        self.assertEqual(ledger.is_leap(2400), True)
        self.assertEqual(ledger.is_leap(2100), False)

    def test_ledger_running_total(self):
        self.assertEqual(ledger.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(ledger.running_total([]), [])
        self.assertEqual(ledger.running_total([5]), [5])
        self.assertEqual(ledger.running_total([2, -2, 2]), [2, 0, 2])

    def test_ledger_format_cents(self):
        self.assertEqual(ledger.format_cents(0), '$0.00')
        self.assertEqual(ledger.format_cents(123456), '$1,234.56')
        self.assertEqual(ledger.format_cents(-105), '-$1.05')
        self.assertEqual(ledger.format_cents(5), '$0.05')
        self.assertEqual(ledger.format_cents(100000000), '$1,000,000.00')

    def test_routes_moving_average(self):
        self.assertEqual(routes.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(routes.moving_average([5], 1), [5.0])
        self.assertEqual(routes.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(routes.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            routes.moving_average([1, 2], 0)

    def test_routes_top_n(self):
        self.assertEqual(routes.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(routes.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(routes.top_n({}, 2), [])
        self.assertEqual(routes.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_digest_tide_line(self):
        self.assertEqual(digest.tide_line(5, 0, 10), {'tide_line': 5})
        self.assertEqual(digest.tide_line(-3, 0, 10), {'tide_line': 0})
        self.assertEqual(digest.tide_line(15, 0, 10), {'tide_line': 10})
        self.assertEqual(digest.tide_line(10, 0, 10), {'tide_line': 10})
        self.assertEqual(digest.tide_line(0, 0, 10), {'tide_line': 0})
        self.assertEqual(digest.tide_line(7, 7, 7), {'tide_line': 7})
        self.assertEqual(digest.tide_line(-20, -30, -10), {'tide_line': -20})

    def test_digest_ferry_summary(self):
        self.assertEqual(digest.ferry_summary('4539 1488 0343 6467'), {'ferry_summary': True})
        self.assertEqual(digest.ferry_summary('79927398713'), {'ferry_summary': True})
        self.assertEqual(digest.ferry_summary('79927398710'), {'ferry_summary': False})
        self.assertEqual(digest.ferry_summary(''), {'ferry_summary': False})
        self.assertEqual(digest.ferry_summary('059'), {'ferry_summary': True})

    def test_digest_keel_summary(self):
        self.assertEqual(digest.keel_summary(95), {'keel_summary': 'A'})
        self.assertEqual(digest.keel_summary(90), {'keel_summary': 'A'})
        self.assertEqual(digest.keel_summary(85), {'keel_summary': 'B'})
        self.assertEqual(digest.keel_summary(80), {'keel_summary': 'B'})
        self.assertEqual(digest.keel_summary(61), {'keel_summary': 'D'})
        self.assertEqual(digest.keel_summary(59), {'keel_summary': 'F'})
        self.assertEqual(digest.keel_summary(0), {'keel_summary': 'F'})

    def test_digest_berth_row(self):
        self.assertEqual(digest.berth_row('the quick brown fox', 2), {'berth_row': 'the quick...'})
        self.assertEqual(digest.berth_row('tea time', 2), {'berth_row': 'tea time'})
        self.assertEqual(digest.berth_row('', 3), {'berth_row': ''})
        self.assertEqual(digest.berth_row('one two three', 1), {'berth_row': 'one...'})

    def test_digest_hull_total(self):
        self.assertEqual(digest.hull_total({'tea': 3, 'milk': 3, 'jam': 1}, 2), {'hull_total': ['milk', 'tea']})
        self.assertEqual(digest.hull_total({'a': 1}, 5), {'hull_total': ['a']})
        self.assertEqual(digest.hull_total({}, 2), {'hull_total': []})
        self.assertEqual(digest.hull_total({'x': 2, 'y': 5, 'z': 2}, 2), {'hull_total': ['y', 'x']})
