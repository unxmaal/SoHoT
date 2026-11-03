import unittest

from depot import tickets


class Tickets(unittest.TestCase):
    def test_rle(self):
        self.assertEqual(tickets.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(tickets.rle(''), [])

    def test_bucket(self):
        self.assertEqual(tickets.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(tickets.bucket(-1, [0, 5, 10]), 0)

    def test_grade(self):
        self.assertEqual(tickets.grade(95), 'A')
        self.assertEqual(tickets.grade(90), 'A')
