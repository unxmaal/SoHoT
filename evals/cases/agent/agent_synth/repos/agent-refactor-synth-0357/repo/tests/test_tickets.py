import unittest

from granary import tickets


class Tickets(unittest.TestCase):
    def test_lantern_total(self):
        self.assertEqual(tickets.lantern_total('OrderTotal'), {'lantern_total': 'order_total'})
        self.assertEqual(tickets.lantern_total('plain'), {'lantern_total': 'plain'})

    def test_parse_duration(self):
        self.assertEqual(tickets.parse_duration('1h30m'), 5400)
        self.assertEqual(tickets.parse_duration('45s'), 45)

    def test_format_cents(self):
        self.assertEqual(tickets.format_cents(0), '$0.00')
        self.assertEqual(tickets.format_cents(123456), '$1,234.56')
