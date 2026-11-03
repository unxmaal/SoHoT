import unittest

from depot import sensors


class Sensors(unittest.TestCase):
    def test_running_total(self):
        self.assertEqual(sensors.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(sensors.running_total([]), [])

    def test_dedupe(self):
        self.assertEqual(sensors.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(sensors.dedupe(['b', 'a', 'b']), ['b', 'a'])

    def test_top_n(self):
        self.assertEqual(sensors.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(sensors.top_n({'a': 1}, 5), ['a'])
