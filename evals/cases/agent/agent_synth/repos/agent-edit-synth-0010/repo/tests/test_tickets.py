import unittest

from quarry import tickets


class Tickets(unittest.TestCase):
    def test_snake_case(self):
        self.assertEqual(tickets.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(tickets.snake_case('plain'), 'plain')
        self.assertEqual(tickets.snake_case('A'), 'a')

    def test_format_cents(self):
        self.assertEqual(tickets.format_cents(0), '$0.00')
        self.assertEqual(tickets.format_cents(123456), '$1,234.56')
        self.assertEqual(tickets.format_cents(-105), '-$1.05')

    def test_percent_change(self):
        self.assertEqual(tickets.percent_change(50, 75), 50.0)
        self.assertEqual(tickets.percent_change(200, 150), -25.0)
        self.assertEqual(tickets.percent_change(80, 80), 0.0)
