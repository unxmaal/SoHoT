import unittest

from compass import sensors


class Sensors(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(sensors.clamp(5, 0, 10), 5)
        self.assertEqual(sensors.clamp(-3, 0, 10), 0)

    def test_format_cents(self):
        self.assertEqual(sensors.format_cents(0), '$0.00')
        self.assertEqual(sensors.format_cents(123456), '$1,234.56')

    def test_dedupe(self):
        self.assertEqual(sensors.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(sensors.dedupe(['b', 'a', 'b']), ['b', 'a'])
