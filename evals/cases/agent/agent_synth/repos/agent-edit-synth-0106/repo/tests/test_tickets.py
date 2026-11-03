import unittest

from wharf import tickets


class Tickets(unittest.TestCase):
    def test_truncate_words(self):
        self.assertEqual(tickets.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(tickets.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(tickets.truncate_words('', 3), '')

    def test_format_cents(self):
        self.assertEqual(tickets.format_cents(0), '$0.00')
        self.assertEqual(tickets.format_cents(123456), '$1,234.56')
        self.assertEqual(tickets.format_cents(-105), '-$1.05')

    def test_snake_case(self):
        self.assertEqual(tickets.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(tickets.snake_case('plain'), 'plain')
        self.assertEqual(tickets.snake_case('A'), 'a')
