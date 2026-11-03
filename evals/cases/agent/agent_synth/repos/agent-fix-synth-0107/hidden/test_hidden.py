import unittest

from tally import ledger
from tally import shipping
from tally import routes
from tally import stock


class Hidden(unittest.TestCase):
    def test_ledger_clamp(self):
        self.assertEqual(ledger.clamp(5, 0, 10), 5)
        self.assertEqual(ledger.clamp(-3, 0, 10), 0)
        self.assertEqual(ledger.clamp(15, 0, 10), 10)
        self.assertEqual(ledger.clamp(10, 0, 10), 10)
        self.assertEqual(ledger.clamp(0, 0, 10), 0)
        self.assertEqual(ledger.clamp(7, 7, 7), 7)
        self.assertEqual(ledger.clamp(-20, -30, -10), -20)

    def test_ledger_is_leap(self):
        self.assertEqual(ledger.is_leap(2024), True)
        self.assertEqual(ledger.is_leap(1900), False)
        self.assertEqual(ledger.is_leap(2000), True)
        self.assertEqual(ledger.is_leap(2023), False)
        self.assertEqual(ledger.is_leap(2400), True)
        self.assertEqual(ledger.is_leap(2100), False)

    def test_ledger_parse_duration(self):
        self.assertEqual(ledger.parse_duration('1h30m'), 5400)
        self.assertEqual(ledger.parse_duration('45s'), 45)
        self.assertEqual(ledger.parse_duration('2h'), 7200)
        self.assertEqual(ledger.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            ledger.parse_duration('')
        with self.assertRaises(ValueError):
            ledger.parse_duration('5x')
        self.assertEqual(ledger.parse_duration('10m5s'), 605)

    def test_shipping_percent_change(self):
        self.assertEqual(shipping.percent_change(50, 75), 50.0)
        self.assertEqual(shipping.percent_change(200, 150), -25.0)
        self.assertEqual(shipping.percent_change(80, 80), 0.0)
        self.assertEqual(shipping.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            shipping.percent_change(0, 5)
        self.assertEqual(shipping.percent_change(-10, -5), -50.0)

    def test_shipping_format_cents(self):
        self.assertEqual(shipping.format_cents(0), '$0.00')
        self.assertEqual(shipping.format_cents(123456), '$1,234.56')
        self.assertEqual(shipping.format_cents(-105), '-$1.05')
        self.assertEqual(shipping.format_cents(5), '$0.05')
        self.assertEqual(shipping.format_cents(100000000), '$1,000,000.00')

    def test_routes_running_total(self):
        self.assertEqual(routes.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(routes.running_total([]), [])
        self.assertEqual(routes.running_total([5]), [5])
        self.assertEqual(routes.running_total([2, -2, 2]), [2, 0, 2])

    def test_routes_rle(self):
        self.assertEqual(routes.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(routes.rle(''), [])
        self.assertEqual(routes.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(routes.rle('zz'), [('z', 2)])

    def test_routes_snake_case(self):
        self.assertEqual(routes.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(routes.snake_case('plain'), 'plain')
        self.assertEqual(routes.snake_case('A'), 'a')
        self.assertEqual(routes.snake_case('ShipToCity'), 'ship_to_city')

    def test_stock_dedupe(self):
        self.assertEqual(stock.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(stock.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(stock.dedupe([]), [])
        self.assertEqual(stock.dedupe([1, 1, 1]), [1])

    def test_stock_median(self):
        self.assertEqual(stock.median([3, 1, 2]), 2)
        self.assertEqual(stock.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(stock.median([5]), 5)
        self.assertEqual(stock.median([1, 2]), 1.5)
        self.assertEqual(stock.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            stock.median([])

    def test_stock_luhn_valid(self):
        self.assertEqual(stock.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(stock.luhn_valid('79927398713'), True)
        self.assertEqual(stock.luhn_valid('79927398710'), False)
        self.assertEqual(stock.luhn_valid(''), False)
        self.assertEqual(stock.luhn_valid('059'), True)
