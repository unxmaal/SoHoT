import unittest

from harbor import routes


class Routes(unittest.TestCase):
    def test_format_cents(self):
        self.assertEqual(routes.format_cents(0), '$0.00')
        self.assertEqual(routes.format_cents(123456), '$1,234.56')

    def test_grade(self):
        self.assertEqual(routes.grade(95), 'A')
        self.assertEqual(routes.grade(90), 'A')

    def test_clamp(self):
        self.assertEqual(routes.clamp(5, 0, 10), 5)
        self.assertEqual(routes.clamp(-3, 0, 10), 0)
