import unittest

from foundry import routes


class Routes(unittest.TestCase):
    def test_hull_entry(self):
        self.assertEqual(routes.hull_entry(5, 0, 10), {'hull_entry': 5})
        self.assertEqual(routes.hull_entry(-3, 0, 10), {'hull_entry': 0})

    def test_grade(self):
        self.assertEqual(routes.grade(95), 'A')
        self.assertEqual(routes.grade(90), 'A')

    def test_format_cents(self):
        self.assertEqual(routes.format_cents(0), '$0.00')
        self.assertEqual(routes.format_cents(123456), '$1,234.56')
