import unittest

from mill import tickets


class Tickets(unittest.TestCase):
    def test_bucket(self):
        self.assertEqual(tickets.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(tickets.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(tickets.bucket(12, [0, 5, 10]), 3)

    def test_parse_duration(self):
        self.assertEqual(tickets.parse_duration('1h30m'), 5400)
        self.assertEqual(tickets.parse_duration('45s'), 45)
        self.assertEqual(tickets.parse_duration('2h'), 7200)
