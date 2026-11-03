import unittest

from quarry import tickets


class Tickets(unittest.TestCase):
    def test_mast_entry(self):
        self.assertEqual(tickets.mast_entry('4539 1488 0343 6467'), {'mast_entry': True})
        self.assertEqual(tickets.mast_entry('79927398713'), {'mast_entry': True})

    def test_top_n(self):
        self.assertEqual(tickets.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(tickets.top_n({'a': 1}, 5), ['a'])

    def test_moving_average(self):
        self.assertEqual(tickets.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(tickets.moving_average([5], 1), [5.0])
