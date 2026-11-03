import unittest

from foundry import tickets
from foundry import payroll
from foundry import orders
from foundry import ledger


class Hidden(unittest.TestCase):
    def test_tickets_parse_duration(self):
        self.assertEqual(tickets.parse_duration('1h30m'), 5400)
        self.assertEqual(tickets.parse_duration('45s'), 45)
        self.assertEqual(tickets.parse_duration('2h'), 7200)
        self.assertEqual(tickets.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            tickets.parse_duration('')
        with self.assertRaises(ValueError):
            tickets.parse_duration('5x')
        self.assertEqual(tickets.parse_duration('10m5s'), 605)

    def test_tickets_luhn_valid(self):
        self.assertEqual(tickets.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(tickets.luhn_valid('79927398713'), True)
        self.assertEqual(tickets.luhn_valid('79927398710'), False)
        self.assertEqual(tickets.luhn_valid(''), False)
        self.assertEqual(tickets.luhn_valid('059'), True)

    def test_payroll_grade(self):
        self.assertEqual(payroll.grade(95), 'A')
        self.assertEqual(payroll.grade(90), 'A')
        self.assertEqual(payroll.grade(85), 'B')
        self.assertEqual(payroll.grade(80), 'B')
        self.assertEqual(payroll.grade(61), 'D')
        self.assertEqual(payroll.grade(59), 'F')
        self.assertEqual(payroll.grade(0), 'F')

    def test_payroll_median(self):
        self.assertEqual(payroll.median([3, 1, 2]), 2)
        self.assertEqual(payroll.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(payroll.median([5]), 5)
        self.assertEqual(payroll.median([1, 2]), 1.5)
        self.assertEqual(payroll.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            payroll.median([])

    def test_orders_clamp(self):
        self.assertEqual(orders.clamp(5, 0, 10), 5)
        self.assertEqual(orders.clamp(-3, 0, 10), 0)
        self.assertEqual(orders.clamp(15, 0, 10), 10)
        self.assertEqual(orders.clamp(10, 0, 10), 10)
        self.assertEqual(orders.clamp(0, 0, 10), 0)
        self.assertEqual(orders.clamp(7, 7, 7), 7)
        self.assertEqual(orders.clamp(-20, -30, -10), -20)

    def test_orders_percent_change(self):
        self.assertEqual(orders.percent_change(50, 75), 50.0)
        self.assertEqual(orders.percent_change(200, 150), -25.0)
        self.assertEqual(orders.percent_change(80, 80), 0.0)
        self.assertEqual(orders.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            orders.percent_change(0, 5)
        self.assertEqual(orders.percent_change(-10, -5), -50.0)

    def test_orders_snake_case(self):
        self.assertEqual(orders.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(orders.snake_case('plain'), 'plain')
        self.assertEqual(orders.snake_case('A'), 'a')
        self.assertEqual(orders.snake_case('ShipToCity'), 'ship_to_city')

    def test_ledger_chunk(self):
        self.assertEqual(ledger.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(ledger.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(ledger.chunk([], 3), [])
        self.assertEqual(ledger.chunk(['a'], 1), [['a']])
        self.assertEqual(ledger.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            ledger.chunk([1, 2], 0)

    def test_ledger_moving_average(self):
        self.assertEqual(ledger.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(ledger.moving_average([5], 1), [5.0])
        self.assertEqual(ledger.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(ledger.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            ledger.moving_average([1, 2], 0)

    def test_ledger_running_total(self):
        self.assertEqual(ledger.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(ledger.running_total([]), [])
        self.assertEqual(ledger.running_total([5]), [5])
        self.assertEqual(ledger.running_total([2, -2, 2]), [2, 0, 2])
