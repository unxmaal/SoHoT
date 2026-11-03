import unittest

from kiln import orders


class Orders(unittest.TestCase):
    def test_hull_total(self):
        self.assertEqual(orders.hull_total('the quick brown fox', 2), {'hull_total': 'the quick...'})
        self.assertEqual(orders.hull_total('tea time', 2), {'hull_total': 'tea time'})

    def test_running_total(self):
        self.assertEqual(orders.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(orders.running_total([]), [])
