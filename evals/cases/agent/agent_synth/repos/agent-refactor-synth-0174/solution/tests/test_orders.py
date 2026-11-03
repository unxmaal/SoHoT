import unittest

from meadow.orders import money


class Orders(unittest.TestCase):
    def test_money(self):
        self.assertEqual(money(0), '$0.00')
        self.assertEqual(money(123456), '$1,234.56')
        self.assertEqual(money(-105), '-$1.05')
