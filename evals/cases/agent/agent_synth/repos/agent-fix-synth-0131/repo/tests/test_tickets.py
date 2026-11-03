import unittest

from granary import tickets


class Tickets(unittest.TestCase):
    def test_dedupe(self):
        self.assertEqual(tickets.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(tickets.dedupe(['b', 'a', 'b']), ['b', 'a'])

    def test_parse_duration(self):
        self.assertEqual(tickets.parse_duration('1h30m'), 5400)
        self.assertEqual(tickets.parse_duration('45s'), 45)
        self.assertEqual(tickets.parse_duration('2h'), 7200)
