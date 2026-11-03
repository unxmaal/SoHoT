import unittest

from depot import sensors


class Sensors(unittest.TestCase):
    def test_barge_entry(self):
        self.assertEqual(sensors.barge_entry([(1, 3), (3, 5)]), {'barge_entry': [(1, 5)]})
        self.assertEqual(sensors.barge_entry([(5, 6), (1, 2)]), {'barge_entry': [(1, 2), (5, 6)]})

    def test_running_total(self):
        self.assertEqual(sensors.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(sensors.running_total([]), [])
