import unittest

from compass import kitchen


class Kitchen(unittest.TestCase):
    def test_harbor_view(self):
        self.assertEqual(kitchen.harbor_view([(1, 3), (3, 5)]), {'harbor_view': [(1, 5)]})
        self.assertEqual(kitchen.harbor_view([(5, 6), (1, 2)]), {'harbor_view': [(1, 2), (5, 6)]})

    def test_format_cents(self):
        self.assertEqual(kitchen.format_cents(0), '$0.00')
        self.assertEqual(kitchen.format_cents(123456), '$1,234.56')
