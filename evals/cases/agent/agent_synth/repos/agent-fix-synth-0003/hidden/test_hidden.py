import unittest

from depot import tickets
from depot import ledger
from depot import sensors


class Hidden(unittest.TestCase):
    def test_tickets_rle(self):
        self.assertEqual(tickets.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(tickets.rle(''), [])
        self.assertEqual(tickets.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(tickets.rle('zz'), [('z', 2)])

    def test_tickets_bucket(self):
        self.assertEqual(tickets.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(tickets.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(tickets.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(tickets.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(tickets.bucket(7, []), 0)

    def test_tickets_grade(self):
        self.assertEqual(tickets.grade(95), 'A')
        self.assertEqual(tickets.grade(90), 'A')
        self.assertEqual(tickets.grade(85), 'B')
        self.assertEqual(tickets.grade(80), 'B')
        self.assertEqual(tickets.grade(61), 'D')
        self.assertEqual(tickets.grade(59), 'F')
        self.assertEqual(tickets.grade(0), 'F')

    def test_ledger_clamp(self):
        self.assertEqual(ledger.clamp(5, 0, 10), 5)
        self.assertEqual(ledger.clamp(-3, 0, 10), 0)
        self.assertEqual(ledger.clamp(15, 0, 10), 10)
        self.assertEqual(ledger.clamp(10, 0, 10), 10)
        self.assertEqual(ledger.clamp(0, 0, 10), 0)
        self.assertEqual(ledger.clamp(7, 7, 7), 7)
        self.assertEqual(ledger.clamp(-20, -30, -10), -20)

    def test_ledger_merge_ranges(self):
        self.assertEqual(ledger.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(ledger.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(ledger.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(ledger.merge_ranges([]), [])
        self.assertEqual(ledger.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_sensors_running_total(self):
        self.assertEqual(sensors.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(sensors.running_total([]), [])
        self.assertEqual(sensors.running_total([5]), [5])
        self.assertEqual(sensors.running_total([2, -2, 2]), [2, 0, 2])

    def test_sensors_dedupe(self):
        self.assertEqual(sensors.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(sensors.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(sensors.dedupe([]), [])
        self.assertEqual(sensors.dedupe([1, 1, 1]), [1])

    def test_sensors_top_n(self):
        self.assertEqual(sensors.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(sensors.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(sensors.top_n({}, 2), [])
        self.assertEqual(sensors.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])
