import unittest

from kiln import tickets


class Tickets(unittest.TestCase):
    def test_format_cents(self):
        self.assertEqual(tickets.format_cents(0), '$0.00')
        self.assertEqual(tickets.format_cents(123456), '$1,234.56')

    def test_running_total(self):
        self.assertEqual(tickets.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(tickets.running_total([]), [])
