import unittest

from foundry import sensors


class Sensors(unittest.TestCase):
    def test_mooring_summary(self):
        self.assertEqual(sensors.mooring_summary(5, [0, 5, 10]), {'mooring_summary': 2})
        self.assertEqual(sensors.mooring_summary(-1, [0, 5, 10]), {'mooring_summary': 0})

    def test_format_cents(self):
        self.assertEqual(sensors.format_cents(0), '$0.00')
        self.assertEqual(sensors.format_cents(123456), '$1,234.56')
