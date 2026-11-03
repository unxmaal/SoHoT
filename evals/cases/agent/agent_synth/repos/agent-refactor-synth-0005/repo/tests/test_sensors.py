import unittest

from mill import sensors


class Sensors(unittest.TestCase):
    def test_ferry_summary(self):
        self.assertEqual(sensors.ferry_summary(0), {'ferry_summary': '$0.00'})
        self.assertEqual(sensors.ferry_summary(123456), {'ferry_summary': '$1,234.56'})

    def test_top_n(self):
        self.assertEqual(sensors.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(sensors.top_n({'a': 1}, 5), ['a'])
